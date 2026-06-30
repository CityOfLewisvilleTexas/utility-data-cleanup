"""
audit_attributes.py
────────────────────────────────────────────────────────────────────────────────
GIS Attribute Completeness Auditor

Reads a tabular GIS attribute export (CSV, XLSX, ODS, TSV, or DBF) and
produces a completeness-audit table for a user-specified list of fields.

For each audited field the script counts features whose value falls into one
of these "missing" categories:

  null          – NaN / None (true typed null; fires reliably when using the
                  library API with a real DataFrame; in CSV/XLSX exports every
                  blank cell is indistinguishable from "", so it lands in
                  "empty" instead — see FORMAT NOTES below)
  empty         – empty string ("") or whitespace-only string
  unknown       – string matching an entry in UNKNOWN_TOKENS (case-insensitive)
                  e.g. "unknown", "unk", "n/a", "na", "none", "?", "tbd" …
  unexpected    – numeric sentinel values (-9999, 0 used as filler, etc.) or
                  string tokens in UNEXPECTED_STR_TOKENS ("null", "nil" …)
  ─────────────────────────────────────────────────────────────────────────────
  total missing – sum of all four categories
  % missing     – (total missing / total features) × 100

FORMAT NOTES
─────────────
  CSV / TSV   Every blank cell is read as an empty string, so "null" will
              always be 0.  All missing values appear in "empty".
  XLSX / ODS  Same behaviour: keep_default_na=False preserves "n/a" / "na"
              as strings (→ "unknown") but collapses truly empty cells to ""
              (→ "empty").  If you need null vs empty separation, pass a
              pandas DataFrame directly to audit_fields().
  DBF         Requires the 'dbfread' package (pip install dbfread).

Usage
─────
  python audit_attributes.py <input_file> <field1> [field2 ...] [options]

Positional arguments:
  input_file        Path to the tabular file (CSV, XLSX, ODS, TSV, DBF)
  fields            One or more field/column names to audit

Options:
  -o, --output FILE           Write the audit table to this file.
                              Supported extensions: .csv  .xlsx  .txt  .md
                              (default: print to stdout)
  -s, --sheet NAME_OR_INDEX   Sheet name or 0-based index for XLSX/ODS files
  -d, --delimiter CHAR        Delimiter for CSV/TSV files (default: auto)
  --unknown-tokens LIST       Comma-separated extra "unknown" string tokens
  --unexpected-tokens LIST    Comma-separated extra "unexpected" string tokens
  --unexpected-numerics LIST  Comma-separated extra numeric sentinel values
  --no-color                  Disable ANSI colour in terminal output
  -v, --verbose               Show per-field value-frequency details

Examples
─────────
  # Audit three fields from a CSV, print results
  python audit_attributes.py water_mains.csv DIAMETER MATERIAL INSTALL_YR

  # Audit from Excel, save to a CSV file
  python audit_attributes.py parcels.xlsx APN OWNER ZONING -o audit.csv

  # Add custom unknown tokens and a numeric sentinel
  python audit_attributes.py pipes.csv MATERIAL \\
      --unknown-tokens "TBD,pending" --unexpected-numerics "0"

────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

# ── Configurable token sets ──────────────────────────────────────────────────

# String values treated as "unknown" (case-insensitive, after stripping)
UNKNOWN_TOKENS: set[str] = {
    "unknown", "unk",
    "n/a", "na", "not available", "not applicable",
    "none", "not known", "not recorded",
    "unspecified", "undefined",
    "?", "-", "--", "---",
    "tbd", "to be determined",
}

# String tokens treated as "unexpected" non-numeric placeholders
UNEXPECTED_STR_TOKENS: set[str] = {
    "null", "nil", "void",
    "#n/a", "#null!", "#value!",
    "missing", "xxx", "x",
    "test", "temp", "placeholder",
}

# Numeric values used as nodata / sentinel markers
UNEXPECTED_NUMERICS: set[float] = {
    -9999.0, -999.0, -99.0, -1.0,
    9999.0, 999.0, 99999.0, 999999.0,
}


# ── Value classifier ─────────────────────────────────────────────────────────

def _classify(
    val: Any,
    unknown_tokens: set[str],
    unexpected_str_tokens: set[str],
    unexpected_numerics: set[float],
) -> str | None:
    """
    Return 'null' | 'empty' | 'unknown' | 'unexpected', or None (= present).
    """
    # ── null ──────────────────────────────────────────────────────────────────
    if val is None:
        return "null"
    if isinstance(val, float) and math.isnan(val):
        return "null"
    try:
        if pd.isna(val):          # catches pd.NA, pd.NaT, np.nan
            return "null"
    except (TypeError, ValueError):
        pass

    # ── string-based checks ───────────────────────────────────────────────────
    if isinstance(val, str):
        stripped = val.strip()

        if stripped == "":
            return "empty"

        lower = stripped.lower()

        if lower in unknown_tokens:
            return "unknown"

        if lower in unexpected_str_tokens:
            return "unexpected"

        # numeric-looking string → check sentinel list
        try:
            fval = float(stripped)
            if fval in unexpected_numerics:
                return "unexpected"
        except ValueError:
            pass

        return None   # valid string value

    # ── numeric checks ────────────────────────────────────────────────────────
    if isinstance(val, (int, float)):
        try:
            if float(val) in unexpected_numerics:
                return "unexpected"
        except (TypeError, ValueError):
            pass

    return None   # valid value


# ── File loader ───────────────────────────────────────────────────────────────

def load_table(
    path: Path,
    sheet: str | int | None = None,
    delimiter: str | None = None,
) -> pd.DataFrame:
    """Load a tabular GIS export into a DataFrame."""
    suffix = path.suffix.lower()

    if suffix in (".xlsx", ".xls", ".ods"):
        kw: dict[str, Any] = {
            "keep_default_na": False,   # preserve "n/a", "na", etc. as strings
            "dtype": str,               # keep every cell as a string
        }
        if sheet is not None:
            kw["sheet_name"] = sheet
        return pd.read_excel(path, **kw)

    if suffix == ".dbf":
        try:
            from dbfread import DBF  # type: ignore
            return pd.DataFrame(iter(DBF(str(path), load=True))).astype(str)
        except ImportError:
            sys.exit(
                "ERROR: dbfread is required to read .dbf files.\n"
                "       Install it with:  pip install dbfread"
            )

    # CSV / TSV / generic delimited text
    csv_kw: dict[str, Any] = {
        "keep_default_na": False,
        "dtype": str,
    }
    if delimiter:
        csv_kw["sep"] = delimiter
    elif suffix == ".tsv":
        csv_kw["sep"] = "\t"
    else:
        csv_kw["sep"] = None        # let pandas sniff the separator
        csv_kw["engine"] = "python"

    return pd.read_csv(path, **csv_kw)


# ── Core audit ────────────────────────────────────────────────────────────────

ROW_LABELS = ["null", "empty", "unknown", "unexpected", "total missing", "% missing"]


def audit_fields(
    df: pd.DataFrame,
    fields: list[str],
    unknown_tokens: set[str] | None = None,
    unexpected_str_tokens: set[str] | None = None,
    unexpected_numerics: set[float] | None = None,
    verbose: bool = False,
) -> pd.DataFrame:
    """
    Return the audit summary as a DataFrame.

    Rows:    null | empty | unknown | unexpected | total missing | % missing
    Columns: one per audited field

    Can be called directly for library / notebook usage:

        from audit_attributes import load_table, audit_fields
        df = load_table(Path("water_mains.csv"))
        result = audit_fields(df, ["DIAMETER", "MATERIAL", "INSTALL_YR"])
        print(result.to_string())
    """
    u_tok  = unknown_tokens        or UNKNOWN_TOKENS
    ux_str = unexpected_str_tokens or UNEXPECTED_STR_TOKENS
    ux_num = unexpected_numerics   or UNEXPECTED_NUMERICS

    total = len(df)
    results: dict[str, dict[str, Any]] = {}

    for field in fields:
        if field not in df.columns:
            print(
                f"  WARNING: field '{field}' not found in the table — skipping.",
                file=sys.stderr,
            )
            results[field] = {lbl: "N/A" for lbl in ROW_LABELS}
            continue

        counts: dict[str, int] = {
            "null": 0, "empty": 0, "unknown": 0, "unexpected": 0
        }

        for val in df[field]:
            cat = _classify(val, u_tok, ux_str, ux_num)
            if cat:
                counts[cat] += 1

        if verbose:
            _print_value_freq(df[field], field)

        total_missing = sum(counts.values())
        pct = (total_missing / total * 100) if total > 0 else 0.0

        results[field] = {
            "null":          counts["null"],
            "empty":         counts["empty"],
            "unknown":       counts["unknown"],
            "unexpected":    counts["unexpected"],
            "total missing": total_missing,
            "% missing":     f"{pct:.1f}%",
        }

    audit_df = pd.DataFrame(results, index=ROW_LABELS)
    audit_df.index.name = f"(n = {total:,})"
    return audit_df


def _print_value_freq(series: pd.Series, field: str, top_n: int = 10) -> None:
    freq = series.value_counts(dropna=False).head(top_n)
    print(f"\n  ── Value frequencies: '{field}' (top {top_n}) ──")
    for val, cnt in freq.items():
        print(f"     {str(val)!r:42s}  {cnt:>6,}")


# ── Output helpers ────────────────────────────────────────────────────────────

# ANSI colour codes (terminal only)
_C = {
    "reset":  "\033[0m",
    "header": "\033[1;36m",   # bold cyan
    "warn":   "\033[1;33m",   # bold yellow  (≥ 20 % missing)
    "ok":     "\033[0;32m",   # green         (< 20 % missing)
}


def _pct_float(val: Any) -> float:
    try:
        return float(str(val).replace("%", ""))
    except (TypeError, ValueError):
        return 0.0


def print_table(
    audit_df: pd.DataFrame,
    use_color: bool = True,
    dest=None,
) -> None:
    """Pretty-print the audit table to *dest* (default: stdout)."""
    out = dest or sys.stdout
    color = use_color and (dest is None) and sys.stdout.isatty()

    fields = list(audit_df.columns)
    col_w  = {f: max(len(f), 14) for f in fields}
    idx_w  = max(len(lbl) for lbl in ROW_LABELS + [audit_df.index.name or ""])
    sep    = "  |  "

    def c(code: str, text: str) -> str:
        return f"{_C[code]}{text}{_C['reset']}" if color else text

    # ── header ────────────────────────────────────────────────────────────────
    hdr = [c("header", (audit_df.index.name or "").ljust(idx_w))]
    for f in fields:
        hdr.append(c("header", f.rjust(col_w[f])))
    print(sep.join(hdr), file=out)

    # ── separator ─────────────────────────────────────────────────────────────
    print(sep.join(["-" * idx_w] + ["-" * col_w[f] for f in fields]), file=out)

    # ── data rows ─────────────────────────────────────────────────────────────
    for lbl in ROW_LABELS:
        row = [lbl.ljust(idx_w)]
        for f in fields:
            val  = audit_df.at[lbl, f]
            cell = str(val).rjust(col_w[f])
            if color and lbl == "% missing" and val != "N/A":
                cell = c("warn" if _pct_float(val) >= 20 else "ok", cell)
            row.append(cell)
        print(sep.join(row), file=out)


def save_output(audit_df: pd.DataFrame, path: Path) -> None:
    suffix = path.suffix.lower()

    if suffix == ".csv":
        audit_df.to_csv(path)

    elif suffix in (".xlsx", ".xls"):
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            audit_df.to_excel(writer, sheet_name="Attribute Audit")
            ws = writer.sheets["Attribute Audit"]
            for col_cells in ws.columns:
                max_len = max(
                    len(str(c.value)) if c.value else 0 for c in col_cells
                )
                ws.column_dimensions[col_cells[0].column_letter].width = max_len + 4

    elif suffix in (".txt", ".md", ""):
        with open(path, "w", encoding="utf-8") as f:
            print_table(audit_df, use_color=False, dest=f)

    else:
        sys.exit(
            f"ERROR: Unsupported output format '{suffix}'.\n"
            "       Supported: .csv  .xlsx  .txt  .md"
        )

    print(f"  ✓  Saved to {path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="audit_attributes",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input_file", type=Path,   help="Tabular input file")
    p.add_argument("fields",     nargs="+",   help="Field names to audit")
    p.add_argument("-o", "--output",    type=Path, metavar="FILE",
                   help="Save audit table (.csv / .xlsx / .txt / .md)")
    p.add_argument("-s", "--sheet",     default=None, metavar="NAME_OR_INDEX",
                   help="Sheet name or 0-based index for Excel/ODS files")
    p.add_argument("-d", "--delimiter", default=None, metavar="CHAR",
                   help="Column delimiter for CSV/TSV (default: auto-detect)")
    p.add_argument("--unknown-tokens",    default="", metavar="LIST",
                   help="Comma-separated extra 'unknown' string tokens")
    p.add_argument("--unexpected-tokens", default="", metavar="LIST",
                   help="Comma-separated extra 'unexpected' string tokens")
    p.add_argument("--unexpected-numerics", default="", metavar="LIST",
                   help="Comma-separated extra numeric sentinel values")
    p.add_argument("--no-color", action="store_true",
                   help="Disable ANSI colour in terminal output")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Print top value-frequency tables for each field")
    return p


def main() -> None:
    args = _build_parser().parse_args()

    if not args.input_file.exists():
        sys.exit(f"ERROR: File not found: {args.input_file}")

    # ── Merge user-supplied tokens ────────────────────────────────────────────
    unknown_tokens = set(UNKNOWN_TOKENS)
    for tok in filter(None, args.unknown_tokens.split(",")):
        unknown_tokens.add(tok.strip().lower())

    unexpected_str_tokens = set(UNEXPECTED_STR_TOKENS)
    for tok in filter(None, args.unexpected_tokens.split(",")):
        unexpected_str_tokens.add(tok.strip().lower())

    unexpected_numerics = set(UNEXPECTED_NUMERICS)
    for tok in filter(None, args.unexpected_numerics.split(",")):
        try:
            unexpected_numerics.add(float(tok.strip()))
        except ValueError:
            print(f"  WARNING: '{tok}' is not a valid number — ignoring.",
                  file=sys.stderr)

    # ── Resolve sheet arg ─────────────────────────────────────────────────────
    sheet: str | int | None = None
    if args.sheet is not None:
        try:
            sheet = int(args.sheet)
        except ValueError:
            sheet = args.sheet

    # ── Load ──────────────────────────────────────────────────────────────────
    print(f"\nLoading: {args.input_file}")
    try:
        df = load_table(args.input_file, sheet=sheet, delimiter=args.delimiter)
    except Exception as exc:
        sys.exit(f"ERROR reading file: {exc}")

    print(f"  {len(df):,} features  ·  {len(df.columns):,} fields total")
    print(f"  Auditing: {', '.join(args.fields)}\n")

    # ── Audit ─────────────────────────────────────────────────────────────────
    audit_df = audit_fields(
        df,
        fields=args.fields,
        unknown_tokens=unknown_tokens,
        unexpected_str_tokens=unexpected_str_tokens,
        unexpected_numerics=unexpected_numerics,
        verbose=args.verbose,
    )

    # ── Display ───────────────────────────────────────────────────────────────
    use_color = not args.no_color
    print_table(audit_df, use_color=use_color)

    if args.output:
        print()
        save_output(audit_df, args.output)

    print()


if __name__ == "__main__":
    main()