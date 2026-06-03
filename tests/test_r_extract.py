"""Tests for R language extraction via tree-sitter-r."""
from pathlib import Path
import pytest
from graphify.extract import extract_r


def _write_r(tmp_path: Path, code: str) -> Path:
    p = tmp_path / "test.R"
    p.write_text(code)
    return p


def _labels(r):
    return [n["label"] for n in r["nodes"]]


def _edges_of(r, relation):
    return [e for e in r["edges"] if e["relation"] == relation]


# ── Builtin / dispatch registration ─────────────────────────────────────────

def test_no_r_builtins_as_nodes(tmp_path):
    """R built-ins (c, list, paste0) must not become free-floating god-nodes."""
    r = extract_r(_write_r(tmp_path, """
f <- function() {
  x <- c(1, 2, 3)
  y <- list(a = 1)
  paste0("hello", "world")
}
"""))
    assert "error" not in r
    labels = _labels(r)
    assert "c()" not in labels
    assert "list()" not in labels
    assert "paste0()" not in labels


def test_R_extension_in_code_extensions():
    from graphify.detect import CODE_EXTENSIONS
    assert ".R" in CODE_EXTENSIONS, ".R must be in CODE_EXTENSIONS for case-sensitive filesystems"


def test_dispatch_includes_r_extensions():
    from graphify.extract import _DISPATCH
    assert ".r" in _DISPATCH
    assert ".R" in _DISPATCH


# ── Grammar loader ───────────────────────────────────────────────────────────

def test_load_r_language_returns_language():
    """Grammar loads without error (requires git and cc on PATH)."""
    from graphify.extract import _load_r_language
    from tree_sitter import Language
    lang = _load_r_language()
    assert isinstance(lang, Language)


# ── extract_r() core functionality ──────────────────────────────────────────

def test_no_error_on_empty_file(tmp_path):
    r = extract_r(_write_r(tmp_path, ""))
    assert "error" not in r


def test_function_definition(tmp_path):
    r = extract_r(_write_r(tmp_path, """
my_func <- function(x, y) {
  x + y
}
"""))
    assert "error" not in r
    assert "my_func()" in _labels(r)


def test_source_import(tmp_path):
    target = tmp_path / "helper.R"
    target.write_text("helper <- function() {}")
    r = extract_r(_write_r(tmp_path, 'source("helper.R")'))
    assert len(_edges_of(r, "imports_from")) == 1


def test_library_import(tmp_path):
    r = extract_r(_write_r(tmp_path, "library(data.table)"))
    pkg_nodes = [n for n in r["nodes"] if "data.table" in n["label"]]
    assert len(pkg_nodes) == 1
    assert len(_edges_of(r, "imports")) == 1


def test_require_import(tmp_path):
    r = extract_r(_write_r(tmp_path, "require(arrow)"))
    pkg_nodes = [n for n in r["nodes"] if "arrow" in n["label"]]
    assert len(pkg_nodes) == 1


def test_namespaced_call(tmp_path):
    r = extract_r(_write_r(tmp_path, """
f <- function() {
  arrow::write_parquet(df, "out.parquet")
}
"""))
    call_edges = [e for e in r["edges"]
                  if e["relation"] == "calls" and "arrow" in e["target"]]
    assert len(call_edges) == 1


def test_right_assign(tmp_path):
    r = extract_r(_write_r(tmp_path, "function(x) { x * 2 } -> doubler"))
    assert "doubler()" in _labels(r)


def test_internal_call(tmp_path):
    r = extract_r(_write_r(tmp_path, """
helper <- function(x) { x + 1 }
main_fn <- function() { helper(5) }
"""))
    call_edges = _edges_of(r, "calls")
    assert any("helper" in e["target"] for e in call_edges)


def test_data_table_walrus_no_crash(tmp_path):
    r = extract_r(_write_r(tmp_path, """
f <- function(dt) {
  dt[, new_col := old_col * 2]
  dt[, c("a", "b") := .(x, y)]
}
"""))
    assert "error" not in r
    assert "f()" in _labels(r)


def test_pipe_operator_no_crash(tmp_path):
    r = extract_r(_write_r(tmp_path, """
f <- function(df) {
  df |> dplyr::filter(x > 0) |> dplyr::select(x, y)
}
"""))
    assert "error" not in r


# ── extract_bash() Rscript integration ──────────────────────────────────────

def test_bash_rscript_links_to_r_file(tmp_path):
    from graphify.extract import extract_bash
    r_script = tmp_path / "pipeline.R"
    r_script.write_text("f <- function() {}")
    sh_file = tmp_path / "run.sh"
    sh_file.write_text('#!/bin/bash\nRscript --vanilla pipeline.R "$1"\n')
    r = extract_bash(sh_file)
    assert "error" not in r
    import_edges = [e for e in r["edges"] if e["relation"] == "imports_from"]
    assert any("pipeline" in e["target"] for e in import_edges), \
        f"Expected imports_from edge to pipeline.R, got: {r['edges']}"
