"""Aegir-shaped /queues lineup — browser e2e against live engine + UI."""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.browser


def test_queues_shell_and_side_nav(page, ui_base):
    page.goto(f"{ui_base}/queues", wait_until="networkidle", timeout=30_000)
    shell = page.locator("#queues-lineup-shell")
    shell.wait_for(state="visible", timeout=15_000)
    assert shell.get_attribute("data-engine-target")

    # Side-nav SECTION roots
    root_sel = page.locator("#lineup-root")
    root_sel.wait_for(state="visible", timeout=15_000)
    options = root_sel.locator("option").all_text_contents()
    joined = " ".join(options).lower()
    assert "current" in joined
    assert "scratch" in joined
    assert "archive" in joined

    # Default trail: single info panel with Flow node on top + Queue Info below
    page.locator(".lineup-panel-aegir").first.wait_for(state="visible", timeout=20_000)
    page.wait_for_timeout(800)
    assert page.locator(".lineup-panel-aegir").count() >= 1
    # Flow node at top of info panel
    assert page.locator(".kumo-flow-self .flow-queue-node, .kumo-flow-self .queue-card").count() >= 1
    # Queue Info fields (yk-web parity)
    info = page.locator(".queue-info-dl").first
    info.wait_for(state="visible", timeout=10_000)
    text = info.inner_text()
    assert any(k in text for k in ("Name", "Status", "Allocated", "Memory")), text[:200]
    # Abs-used shown on the flow node
    abs_txt = page.locator(".queue-card-abs").first.inner_text()
    assert "%" in abs_txt or "n/a" in abs_txt.lower()


def test_open_children_then_child_info(page, ui_base):
    page.goto(
        f"{ui_base}/queues?root=current&partition=default&open=qinfo:root",
        wait_until="networkidle",
        timeout=30_000,
    )
    page.locator(".lineup-panel-aegir").first.wait_for(state="visible", timeout=20_000)
    page.wait_for_timeout(800)
    # Click root flow node → children panel
    root_node = page.locator(".kumo-flow-self .flow-queue-node, .kumo-flow-self .queue-card").first
    root_node.click()
    page.wait_for_timeout(500)
    assert page.locator(".kumo-flow-children, .kumo-flow-stack").count() >= 1
    card = page.locator(".kumo-flow-children .queue-card, .kumo-flow-stack .queue-card").first
    if card.count() == 0:
        pytest.skip("no child queue cards")
    # Child card shows status + abs used
    card_text = card.inner_text()
    assert "Active" in card_text or "leaf" in card_text or "%" in card_text
    card.click()
    page.wait_for_timeout(500)
    # Child info panel uses same layout (flow on top + info)
    assert page.locator(".queue-info-dl").count() >= 1
    assert page.locator(".kumo-flow-self").count() >= 1


def test_policy_config_seed(page, ui_base):
    page.goto(f"{ui_base}/queues", wait_until="networkidle", timeout=30_000)
    page.locator("#lineup-rail").wait_for(state="visible", timeout=15_000)
    seed = page.locator('#lineup-rail a[data-seed="config/queues"]')
    seed.wait_for(state="visible", timeout=10_000)
    seed.click()
    page.locator(".lineup-panel-aegir").first.wait_for(state="visible", timeout=15_000)
    body = page.locator(".lineup-note-body").inner_text(timeout=10_000)
    assert "partitions" in body or "queues.yaml" in body.lower() or "yaml" in body.lower()


def test_ops_health_virtual_note(page, ui_base):
    page.goto(
        f"{ui_base}/queues?root=current&open=ops/health",
        wait_until="networkidle",
        timeout=30_000,
    )
    page.locator(".lineup-panel-aegir").first.wait_for(state="visible", timeout=20_000)
    text = page.locator(".lineup-panel-aegir-body").first.inner_text(timeout=10_000)
    assert re.search(r"healthy|unhealthy|Scheduling|health", text, re.I)


def test_switch_root_to_scratch(page, ui_base):
    page.goto(f"{ui_base}/queues?root=current", wait_until="networkidle", timeout=30_000)
    page.locator("#lineup-root").wait_for(state="visible", timeout=15_000)
    page.locator("#lineup-root").select_option("scratch")
    page.wait_for_timeout(800)
    # root select stays on scratch; canvas still mounts
    assert page.locator("#lineup-root").input_value() == "scratch"
    page.locator("#lineup-canvas").wait_for(state="visible")


def test_nodes_redirect_opens_virtual_note(page, ui_base):
    page.goto(f"{ui_base}/nodes", wait_until="networkidle", timeout=30_000)
    assert "ops/nodes" in page.url or "open=" in page.url
    page.locator(".lineup-panel-aegir, #queues-lineup-shell").first.wait_for(
        state="visible", timeout=20_000
    )
