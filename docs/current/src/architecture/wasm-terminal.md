# WASM Terminal

A Ghostty-based terminal component compiled to WebAssembly, embedded in the bottom half of the web interface. User instructions entered in the terminal transit gRPC to the server engine and responses stream back to the client.

## Design

The terminal provides a familiar command-line experience in the browser. Users type natural language instructions or structured commands, which are sent to the gRPC engine. The engine processes the instruction, potentially directing compute workloads, and streams responses back to the terminal.

This approach provides:

- **Zero install** — runs entirely in the browser via WASM
- **Full terminal capabilities** — Ghostty's terminal emulation compiled to WASM
- **Bidirectional streaming** — gRPC streams carry instructions and responses
- **Session persistence** — terminal state survives page navigation

## WASM Toolchain

The build toolchain (configured in devenv.nix):

| Tool | Purpose |
|------|---------|
| `wasmtime` | WASM runtime for testing |
| `wasm-pack` | Build Rust → WASM packages |
| `wasm-bindgen-cli` | Generate JS bindings |
| `binaryen` | WASM optimization (wasm-opt) |

## Web Interface Layout

```d2
direction: down

browser: Web Interface {
  viz: HoloViews Visualization {
    tooltip: "agent-mediated, top half"
    style.fill: "#e8f4f8"
  }
  term: Ghostty WASM Terminal {
    tooltip: "user interaction, bottom half"
    style.fill: "#f0f0f0"
  }
  viz -> term: {style.stroke-dash: 3}
}
```

Instructions flow from the terminal through gRPC to the engine. The engine directs Dask/Datashader to recompute views, which are streamed to the visualization panel above the terminal.
