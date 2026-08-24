use std::path::PathBuf;
use std::process::Command;

fn fixture() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/data/sdg_machine_small.h5")
}

#[test]
fn hdf5_count_machine_analog() {
    let bin = env!("CARGO_BIN_EXE_signals-df");
    let out = Command::new(bin)
        .args([
            "hdf5",
            "--file",
            fixture().to_str().unwrap(),
            "--sql",
            "SELECT COUNT(*) AS n FROM gpu_power",
        ])
        .output()
        .expect("run signals-df hdf5");
    let stderr = String::from_utf8_lossy(&out.stderr);
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        out.status.success(),
        "status={} stderr={stderr} stdout={stdout}",
        out.status
    );
    assert!(
        stdout.contains("512"),
        "expected 512 rows in\n{stdout}"
    );
}

#[test]
fn hdf5_missing_file_is_guru() {
    let bin = env!("CARGO_BIN_EXE_signals-df");
    let out = Command::new(bin)
        .args(["hdf5", "--file", "/no/such/machine.h5"])
        .output()
        .expect("run");
    assert!(!out.status.success());
    let err = format!(
        "{}{}",
        String::from_utf8_lossy(&out.stderr),
        String::from_utf8_lossy(&out.stdout)
    );
    assert!(err.contains("#SL.00000018"), "{err}");
}
