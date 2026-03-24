"""Tests for the SVM short-text classifier."""

from __future__ import annotations

import pytest


@pytest.fixture
def training_data():
    """Minimal training set for SVM testing."""
    texts = [
        "email address | user@example.com, admin@test.org",
        "email | john@company.com, jane@example.net",
        "contact email | support@help.com",
        "phone number | +1-555-123-4567, (800) 555-0199",
        "telephone | 555-0100, 555-0101, 555-0102",
        "mobile phone | +44 20 7123 4567",
        "payment card number | 4111111111111111, 5500000000000004",
        "credit card | 4532015112830366, 6011514433546201",
        "card number | 378282246310005",
        "tax identifier | 123-45-6789, 987-65-4321",
        "ssn | 111-22-3333, 444-55-6666",
        "social security number | 078-05-1120",
    ]
    labels = [
        "0076", "0076", "0076",   # EmailAddress
        "0074", "0074", "0074",   # PhoneNumber
        "0070", "0070", "0070",   # PaymentCardData
        "0085", "0085", "0085",   # TaxIdentifier
    ]
    return texts, labels


class TestSVMClassifier:
    def test_fit_and_predict(self, training_data):
        """SVM trains and produces probability dicts."""
        from sigint.svm_classifier import SVMClassifier

        texts, labels = training_data
        svm = SVMClassifier()
        svm.fit(texts, labels)

        proba = svm.predict_proba(["email | test@example.com"])
        assert len(proba) == 1
        assert isinstance(proba[0], dict)
        assert sum(proba[0].values()) == pytest.approx(1.0, abs=0.01)

    def test_predict_single(self, training_data):
        """predict_proba_single returns a single dict."""
        from sigint.svm_classifier import SVMClassifier

        texts, labels = training_data
        svm = SVMClassifier()
        svm.fit(texts, labels)

        proba = svm.predict_proba_single("phone | 555-0123")
        assert isinstance(proba, dict)
        assert len(proba) > 0

    def test_correct_class_highest(self, training_data):
        """The correct class should get the highest probability."""
        from sigint.svm_classifier import SVMClassifier

        texts, labels = training_data
        svm = SVMClassifier()
        svm.fit(texts, labels)

        # Email should predict EmailAddress (0076)
        proba = svm.predict_proba_single("email address | admin@corp.com")
        best = max(proba, key=proba.get)
        assert best == "0076"

        # Phone should predict PhoneNumber (0074)
        proba = svm.predict_proba_single("phone number | 555-123-4567")
        best = max(proba, key=proba.get)
        assert best == "0074"

    def test_not_fitted_raises(self):
        """Predict before fit raises RuntimeError."""
        from sigint.svm_classifier import SVMClassifier

        svm = SVMClassifier()
        with pytest.raises(RuntimeError, match="must be fitted"):
            svm.predict_proba(["test"])

    def test_is_fitted_property(self, training_data):
        """is_fitted reflects training state."""
        from sigint.svm_classifier import SVMClassifier

        svm = SVMClassifier()
        assert not svm.is_fitted

        texts, labels = training_data
        svm.fit(texts, labels)
        assert svm.is_fitted

    def test_save_and_load(self, training_data, tmp_path):
        """Round-trip persistence via save/load."""
        from sigint.svm_classifier import SVMClassifier

        texts, labels = training_data
        svm = SVMClassifier()
        svm.fit(texts, labels)

        model_path = tmp_path / "svm_model.pkl"
        svm.save(model_path)
        assert model_path.exists()
        assert model_path.with_suffix(".classes.json").exists()

        loaded = SVMClassifier.load(model_path)
        assert loaded.is_fitted

        # Predictions should match
        original = svm.predict_proba_single("email | test@test.com")
        restored = loaded.predict_proba_single("email | test@test.com")
        for code in original:
            assert abs(original[code] - restored.get(code, 0)) < 1e-6

    def test_custom_config(self, training_data):
        """Custom SVMConfig parameters are respected."""
        from sigint.svm_classifier import SVMClassifier, SVMConfig

        texts, labels = training_data
        config = SVMConfig(
            char_ngram_min=2,
            char_ngram_max=4,
            max_features=1000,
            svc_C=0.5,
        )
        svm = SVMClassifier(config=config)
        svm.fit(texts, labels)

        proba = svm.predict_proba_single("email | user@example.com")
        assert isinstance(proba, dict)
        assert sum(proba.values()) == pytest.approx(1.0, abs=0.01)


class TestSVMWithDST:
    """Integration: SVM probabilities → mass function → Dempster combination."""

    def test_svm_mass_in_combination(self, training_data):
        """SVM mass combines with cosine mass via Dempster's rule."""
        from sigint.belief import FrameOfDiscernment, dempster_combine
        from sigint.category_set import sigdg_category_set
        from sigint.mass_functions import cosine_to_mass, svm_to_mass
        from sigint.svm_classifier import SVMClassifier

        cs = sigdg_category_set(hierarchical=True)
        frame = FrameOfDiscernment(cs)

        # Train SVM
        texts, labels = training_data
        svm = SVMClassifier()
        svm.fit(texts, labels)

        # Get SVM proba for an email column
        svm_proba = svm.predict_proba_single("email address | user@test.com")

        # Build mass functions
        cosine_sims = {"0076": 0.9, "0085": 0.1}
        m_cosine = cosine_to_mass(cosine_sims, frame, discount=0.3)
        m_svm = svm_to_mass(svm_proba, frame, discount=0.2)

        # Both should be valid
        assert m_cosine.is_valid
        assert m_svm.is_valid

        # Combine via Dempster's rule
        combined, k = dempster_combine(m_cosine, m_svm)
        assert combined.is_valid
        assert 0 <= k < 1

        # Agreement on email should produce high combined mass
        email_mass = combined.masses.get(frame.singleton("0076"), 0.0)
        assert email_mass > 0.3

    def test_five_source_combination(self, training_data):
        """All 5 sources combine without error."""
        from sigint.belief import FrameOfDiscernment, combine_multiple
        from sigint.category_set import sigdg_category_set
        from sigint.mass_functions import (
            catboost_to_mass,
            cosine_to_mass,
            name_match_to_mass,
            pattern_to_mass,
            svm_to_mass,
        )
        from sigint.svm_classifier import SVMClassifier

        cs = sigdg_category_set(hierarchical=True)
        frame = FrameOfDiscernment(cs)

        # 1. Cosine
        m1 = cosine_to_mass({"0076": 0.8, "0085": 0.1}, frame)
        # 2. CatBoost
        m2 = catboost_to_mass({"0076": 0.7, "0085": 0.2, "0074": 0.1}, frame)
        # 3. Pattern
        m3 = pattern_to_mass(["email_pattern"], frame)
        # 4. Name match
        m4 = name_match_to_mass("email_address", frame, cs)
        # 5. SVM
        texts, labels = training_data
        svm = SVMClassifier()
        svm.fit(texts, labels)
        svm_proba = svm.predict_proba_single("email address | user@test.com")
        m5 = svm_to_mass(svm_proba, frame)

        # Combine all 5
        combined, k = combine_multiple([m1, m2, m3, m4, m5])
        assert combined.is_valid
        assert 0 <= k < 1

        # Email should dominate with 5 agreeing sources
        betp_email = combined.pignistic_probability(frame.singleton("0076"))
        assert betp_email > 0.8
