import os
import pandas as pd
import re
from typing import Optional, Union, List, Tuple, Dict
from pathlib import Path


def read_csv_to_dataframe(file_path: str) -> pd.DataFrame:
    """
    Read a CSV file and convert it to a pandas DataFrame.

    Parameters
    ----------
    file_path : str
        Path to the CSV file to be read.

    Returns
    -------
    pd.DataFrame
        DataFrame containing the CSV data.

    Raises
    ------
    FileNotFoundError
        If the specified file does not exist.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    return pd.read_csv(file_path)


def join_dataframes(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    join_field_a: str,
    join_field_b: str,
    how: str = 'left'
) -> pd.DataFrame:
    """
    Join two DataFrames on specified columns.

    Table A contains non-unique values in the join field (many side),
    while Table B contains unique values (one side), creating a
    many-to-one or one-to-many relationship.

    Parameters
    ----------
    df_a : pd.DataFrame
        The first DataFrame (with non-unique join values).
    df_b : pd.DataFrame
        The second DataFrame (with unique join values).
    join_field_a : str
        Column name in df_a to join on.
    join_field_b : str
        Column name in df_b to join on.
    how : str, optional
        Type of join operation ('left', 'right', 'inner', 'outer').
        Default is 'left'.

    Returns
    -------
    pd.DataFrame
        Joined DataFrame.

    Raises
    ------
    ValueError
        If join fields don't exist in their respective DataFrames.
    """
    if join_field_a not in df_a.columns:
        raise ValueError(f"Column '{join_field_a}' not found in Table A")
    if join_field_b not in df_b.columns:
        raise ValueError(f"Column '{join_field_b}' not found in Table B")

    return df_a.merge(
        df_b,
        left_on=join_field_a,
        right_on=join_field_b,
        how=how,
        suffixes=('', '_from_b')
    )


def parse_date_series(date_series: pd.Series) -> pd.Series:
    """
    Parse date values from a text field into pandas datetime.

    Handles:
    - NULL / blank / '-' placeholders
    - whitespace
    - mm/dd/yy (e.g. 08/01/04) -> 2004-08-01
    - mm/dd/yyyy
    - rejects implausible years (> current year + 1)

    Returns
    -------
    pd.Series of datetime64[ns] with NaT for invalid/unparseable values.
    """
    s = date_series.astype(str).str.strip()

    # normalize placeholders
    s = s.replace({
        "": pd.NA,
        "NULL": pd.NA,
        "null": pd.NA,
        "NaN": pd.NA,
        "nan": pd.NA,
        "-": pd.NA
    })

    # helper: expand mm/dd/yy to mm/dd/yyyy (assume 00–29 = 2000s, 30–99 = 1900s)
    def expand_two_digit_year(val: str) -> str:
        if pd.isna(val):
            return val

        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2})", val)
        if not m:
            return val

        mm, dd, yy = m.groups()
        yy = int(yy)

        if yy <= 29:
            yyyy = 2000 + yy
        else:
            yyyy = 1900 + yy

        return f"{int(mm):02d}/{int(dd):02d}/{yyyy}"

    s = s.apply(expand_two_digit_year)

    dt = pd.to_datetime(s, errors="coerce", format="%m/%d/%Y")

    # reject implausible years (like 3015)
    current_year = pd.Timestamp.now().year
    dt = dt.where(dt.dt.year.between(1900, current_year + 1))

    return dt


def prepare_table_b_mode_date_lookup(
    df_b: pd.DataFrame,
    join_field_b: str,
    date_field_b: str,
    output_date_field_name: str,
    tie_break: str = "earliest"
) -> pd.DataFrame:
    """
    Build a lookup table from Table B containing one row per join value
    with the MOST FREQUENTLY OCCURRING valid date found in `date_field_b`.

    If multiple dates are tied for most frequent, tie_break determines which
    date is chosen:
      - "earliest" (default): choose the earliest among the tied dates
      - "latest": choose the latest among the tied dates

    Parameters
    ----------
    df_b : pd.DataFrame
        Source Table B.
    join_field_b : str
        Join key column in Table B.
    date_field_b : str
        Date field in Table B to parse and reduce.
    output_date_field_name : str
        Name of the resulting chosen date column (e.g., 'MODE_AsBuiltDate').
    tie_break : str, optional
        Tie-breaking rule for equally frequent dates ("earliest" or "latest").

    Returns
    -------
    pd.DataFrame
        DataFrame with [join_field_b, output_date_field_name].
    """
    df_b_copy = df_b.copy()

    # Normalize join field in B
    df_b_copy[join_field_b] = df_b_copy[join_field_b].astype(str).str.strip()
    df_b_copy.loc[df_b_copy[join_field_b].isin(["", "nan", "None"]), join_field_b] = pd.NA
    df_b_copy = df_b_copy[df_b_copy[join_field_b].notna()].copy()

    # Parse dates
    df_b_copy["_parsed_date"] = parse_date_series(df_b_copy[date_field_b])
    df_b_with_dates = df_b_copy[df_b_copy["_parsed_date"].notna()].copy()

    if df_b_with_dates.empty:
        return pd.DataFrame(columns=[join_field_b, output_date_field_name])

    # Count occurrences of each date per join key
    counts = (
        df_b_with_dates
        .groupby([join_field_b, "_parsed_date"])
        .size()
        .reset_index(name="date_count")
    )

    # For each join key, pick the date with max count, then break ties deterministically
    if tie_break not in ("earliest", "latest"):
        raise ValueError("tie_break must be 'earliest' or 'latest'.")

    # Sort so the "best" row per project is first:
    # - highest frequency first (descending)
    # - then earliest or latest date depending on tie_break
    if tie_break == "earliest":
        counts = counts.sort_values(
            by=[join_field_b, "date_count", "_parsed_date"],
            ascending=[True, False, True]
        )
    else:  # latest
        counts = counts.sort_values(
            by=[join_field_b, "date_count", "_parsed_date"],
            ascending=[True, False, False]
        )

    # Take first row per join key after sorting
    mode_dates = (
        counts
        .groupby(join_field_b, as_index=False)
        .first()
        .rename(columns={"_parsed_date": output_date_field_name})
        [[join_field_b, output_date_field_name]]
    )

    return mode_dates


# TODO - remove if unused?
def prepare_table_b_earliest_date_lookup(
    df_b: pd.DataFrame,
    join_field_b: str,
    date_field_b: str,
    output_date_field_name: str
) -> pd.DataFrame:
    """
    Build a lookup table from Table B containing one row per join value
    with the earliest valid date found in `date_field_b`.

    Parameters
    ----------
    df_b : pd.DataFrame
        Source Table B.
    join_field_b : str
        Join key column in Table B.
    date_field_b : str
        Date field in Table B to parse and reduce.
    output_date_field_name : str
        Name of the resulting earliest date column (e.g., 'EARLIEST_AsBuiltDate').

    Returns
    -------
    pd.DataFrame
        DataFrame with [join_field_b, output_date_field_name].
    """
    df_b_copy = df_b.copy()

    # Normalize join field in B
    df_b_copy[join_field_b] = df_b_copy[join_field_b].astype(str).str.strip()
    df_b_copy.loc[df_b_copy[join_field_b].isin(["", "nan", "None"]), join_field_b] = pd.NA
    df_b_copy = df_b_copy[df_b_copy[join_field_b].notna()].copy()

    # Parse dates
    df_b_copy["_parsed_date"] = parse_date_series(df_b_copy[date_field_b])

    df_b_with_dates = df_b_copy[df_b_copy["_parsed_date"].notna()].copy()

    # Earliest parsed date per join key
    earliest = (
        df_b_with_dates
        .groupby(join_field_b, as_index=False)["_parsed_date"]
        .min()
        .rename(columns={"_parsed_date": output_date_field_name})
    )

    return earliest


def add_source_field(
    df: pd.DataFrame,
    source_field_name: str,
    default_value: str = ''
) -> pd.DataFrame:
    """
    Add a new text field to store data source explanation.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to add the field to.
    source_field_name : str
        Name of the new source field to be created.
    default_value : str, optional
        Default value for the new field. Default is empty string.

    Returns
    -------
    pd.DataFrame
        DataFrame with the new source field added.
    """
    df_result = df.copy()
    if source_field_name not in df_result.columns:
        df_result[source_field_name] = default_value
    return df_result


def update_dates_conditionally(
    df: pd.DataFrame,
    date_field_a: str,
    date_field_b: str,
    source_field: str,
    source_field_value: str
) -> pd.DataFrame:
    """
    Update date_field_a with date_field_b only where date_field_a is missing/invalid.
    Writes source_field_value into source_field only when date_field_a is updated.
    """
    df_result = df.copy()

    # Normalize A date field (treat blank/NaN/'NaN' as null)
    a_raw = df_result[date_field_a].astype(str).str.strip()
    a_raw = a_raw.replace({'': pd.NA, 'NaN': pd.NA, 'nan': pd.NA, 'None': pd.NA})
    df_result['_a_dt'] = pd.to_datetime(a_raw, errors='coerce')

    # remove dates with years in the future (TODO: do this by date, not just year?)
    current_year = pd.Timestamp.now().year
    df_result['_a_dt'] = df_result['_a_dt'].where(
        df_result['_a_dt'].dt.year.between(1900, current_year + 1)
    )

    # date_field_b should already be a datetime column, but coerce just in case
    df_result["_b_dt"] = pd.to_datetime(df_result[date_field_b], errors="coerce")

    needs_update = df_result['_a_dt'].isna() & df_result['_b_dt'].notna()

    # Apply updates
    df_result.loc[needs_update, date_field_a] = df_result.loc[needs_update, '_b_dt'].dt.strftime('%Y-%m-%d')
    df_result.loc[needs_update, source_field] = source_field_value

    # Cleanup
    df_result = df_result.drop(columns=['_a_dt', '_b_dt'])
    return df_result


def _normalize_date_field_config(
    date_field_config: Union[
        Dict[str, str],
        List[Tuple[str, str]]
    ]
) -> List[Tuple[str, str]]:
    """
    Normalize a dict or list config into a list of (date_field_b, source_field_value)
    preserving user-specified ordering.

    Parameters
    ----------
    date_field_config : dict or list
        Either:
          - dict: {"AsBuiltDate": "Project As-Built Date", "AcceptDate": "Project Accept Date"}
          - list: [("AsBuiltDate","Project As-Built Date"), ("AcceptDate","Project Accept Date")]

    Returns
    -------
    list of tuples
        [(date_field_b, source_field_value), ...]
    """
    if isinstance(date_field_config, dict):
        return list(date_field_config.items())
    elif isinstance(date_field_config, list):
        return date_field_config
    else:
        raise ValueError("date_field_config must be a dict or a list of tuples.")


def process_csv_files(
    csv_file_a: str,
    csv_file_b: str,
    join_field_a: str,
    join_field_b: str,
    date_field_a: str,
    date_field_config: Union[
        Dict[str, str],
        List[Tuple[str, str]]
    ],
    source_field_name: str,
    output_file: Optional[str] = None
) -> pd.DataFrame:
    """
    Main orchestration function to process two CSV files, supporting multiple date fields from Table B.

    Workflow:
    1) Read Table A and normalize join keys.
    2) Read Table B.
    3) For each date field in date_field_config:
        a) Build earliest-date lookup from Table B
        b) Merge lookup into working dataframe
        c) Update Table A date field only where it is missing/invalid
        d) If updated, write the corresponding source label
    4) Optionally save output.

    Parameters
    ----------
    csv_file_a : str
        Path to CSV file A (with non-unique join values).
    csv_file_b : str
        Path to CSV file B (with unique join values).
    join_field_a : str
        Column name in Table A to join on.
    join_field_b : str
        Column name in Table B to join on.
    date_field_a : str
        Date field name in Table A to be updated.
    date_field_config : dict or list of tuples
        Configuration for using multiple date fields in Table B, in priority order.

        Examples:
        - dict:
          {"AsBuiltDate": "Project As-Built Date", "AcceptDate": "Project Accept Date"}

        - list:
          [("AsBuiltDate","Project As-Built Date"), ("AcceptDate","Project Accept Date")]

        The order matters; earlier fields are used first.
    source_field_name : str
        Field in output that describes where the date came from.
    output_file : str, optional
        Path to save the output CSV. If None, file is not saved.

    Returns
    -------
    pd.DataFrame
        Processed DataFrame with updated dates and source information.
    """
    date_field_pairs = _normalize_date_field_config(date_field_config)

    # Step 1: Read CSV files
    df_a = read_csv_to_dataframe(csv_file_a)

    # Normalize join field in A
    df_a[join_field_a] = df_a[join_field_a].astype(str).str.strip()
    df_a.loc[df_a[join_field_a].isin(["", "nan", "None"]), join_field_a] = pd.NA
    df_a[join_field_a] = df_a[join_field_a].str.replace(r"\.0$", "", regex=True)

    df_b = read_csv_to_dataframe(csv_file_b)

    print(f"Table A records: {len(df_a)}")
    print(f"Table B records: {len(df_b)}")

    # Step 2: start working df and add source field
    df_working = add_source_field(df_a, source_field_name)

    # Step 3: loop through date field pairs in priority order
    for date_field_b, source_value in date_field_pairs:
        lookup_col = f"MODE_{date_field_b}"

        if date_field_b not in df_b.columns:
            print(f"WARNING: Table B does not have field '{date_field_b}'. Skipping.")
            continue

        # Build mode (most frequently-occurring) lookup for this date field
        lookup = prepare_table_b_mode_date_lookup(
            df_b=df_b,
            join_field_b=join_field_b,
            date_field_b=date_field_b,
            output_date_field_name=lookup_col,
            tie_break="earliest"
        )

        print(f"Lookup built for {date_field_b}: {len(lookup)} project rows with valid dates")

        # Merge lookup into working df
        df_working = df_working.merge(
            lookup,
            left_on=join_field_a,
            right_on=join_field_b,
            how="left"
        )

        # Update using this field (only fills missing/invalid in A)
        before_count = (df_working[source_field_name] == source_value).sum()

        df_working = update_dates_conditionally(
            df_working,
            date_field_a=date_field_a,
            date_field_b=lookup_col,
            source_field=source_field_name,
            source_field_value=source_value
        )

        after_count = (df_working[source_field_name] == source_value).sum()
        print(f"Applied {date_field_b} -> updated {(after_count - before_count)} records")

        # Optionally drop the lookup column to keep output clean
        df_working = df_working.drop(columns=[lookup_col, join_field_b], errors="ignore")

    # Step 4: Optional save
    if output_file:
        df_working.to_csv(output_file, index=False)
        print(f"Results saved to {output_file}")

    return df_working


if __name__ == "__main__":
    dirname = os.path.dirname(__file__)
    csv_file_b = os.path.join(dirname, r'csv\as-built-project-table-20251217.csv')

    # sewer lines
    csv_file_a = os.path.join(dirname, r'csv\sewer-lines-table-20260106.csv')
    output_file = os.path.join(dirname, r'csv\sewer-lines-table-20260106-updated-with-mode-dates.csv')

    # water lines
    #csv_file_a = os.path.join(dirname, r'csv\water-lines-table-20260106.csv')
    #output_file = os.path.join(dirname, r'csv\water-lines-table-20260106-updated-with-mode-dates.csv')

    join_field_a = 'PROJECT'
    join_field_b = 'ProjectNumber'
    date_field_a = 'ASB_DATE'

    # config can be dict or list but list is safer for all versions of Python (dict ordering is preserved in Python 3.7+):
    date_field_config = [
        ("AsBuiltDate", "Project As-Built Date"),
        ("AcceptDate", "Project Accept Date"),
    ]

    source_field_name = 'As_Built_Date_Source'
    
    result = process_csv_files(
        csv_file_a=csv_file_a,
        csv_file_b=csv_file_b,
        join_field_a=join_field_a,
        join_field_b=join_field_b,
        date_field_a=date_field_a,
        date_field_config=date_field_config,
        source_field_name=source_field_name,
        output_file=output_file
    )

    print(f"Processed {len(result)} records")
    print(f"Updated {(result[source_field_name] != '').sum()} dates")
