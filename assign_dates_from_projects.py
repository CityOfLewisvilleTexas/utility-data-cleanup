import os
import pandas as pd
import re
from typing import Optional
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
    Parse date values from Table B into pandas datetime.

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


def prepare_table_b_with_earliest_dates(df_b, join_field_b, date_field_b):
    df_b_copy = df_b.copy()

    # Normalize join field in B
    df_b_copy[join_field_b] = df_b_copy[join_field_b].astype(str).str.strip()
    df_b_copy.loc[df_b_copy[join_field_b].isin(["", "nan", "None"]), join_field_b] = pd.NA
    df_b_copy = df_b_copy[df_b_copy[join_field_b].notna()].copy()

    print(f"Table B records after removing null join values: {len(df_b_copy)}")

    # Parse dates robustly
    df_b_copy["_parsed_date"] = parse_date_series(df_b_copy[date_field_b])

    df_b_with_dates = df_b_copy[df_b_copy["_parsed_date"].notna()].copy()

    print(f"Table B records with valid dates: {len(df_b_with_dates)}")
    print(f"Unique join values with valid dates: {df_b_with_dates[join_field_b].nunique()}")

    # Earliest parsed date per join key
    earliest = (
        df_b_with_dates
        .groupby(join_field_b, as_index=False)["_parsed_date"]
        .min()
        .rename(columns={"_parsed_date": "EARLIEST_DATE"})
    )

    print(f"Groups after getting earliest date per join value: {len(earliest)}")
    return earliest



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

    print(f"\n=== Diagnostic Info ===")
    print(f"Total records in joined table: {len(df_result)}")

    # Normalize A date field (treat blank/NaN/'NaN' as null)
    a_raw = df_result[date_field_a].astype(str).str.strip()
    a_raw = a_raw.replace({'': pd.NA, 'NaN': pd.NA, 'nan': pd.NA, 'None': pd.NA})
    df_result['_a_dt'] = pd.to_datetime(a_raw, errors='coerce')
    # remove dates with years in the future (TODO: do this by date, not just year?)
    current_year = pd.Timestamp.now().year
    df_result['_a_dt'] = df_result['_a_dt'].where(
        df_result['_a_dt'].dt.year.between(1900, current_year + 1)
        )

    # Normalize B date field
    #b_raw = df_result[date_field_b].astype(str).str.strip()
    #b_raw = b_raw.replace({'': pd.NA, '-': pd.NA, 'NaN': pd.NA, 'nan': pd.NA, 'None': pd.NA})
    #df_result['_b_dt'] = pd.to_datetime(b_raw, errors='coerce', infer_datetime_format=True)
    df_result["_b_dt"] = pd.to_datetime(df_result[date_field_b], errors="coerce")

    print(f"Records where {date_field_a} is null after conversion: {df_result['_a_dt'].isna().sum()}")
    print(f"Records where {date_field_b} has valid datetime: {df_result['_b_dt'].notna().sum()}")

    # A needs update if missing AND B has a valid earliest date
    needs_update = df_result['_a_dt'].isna() & df_result['_b_dt'].notna()

    print(f"Records that need update: {needs_update.sum()}")

    # Apply updates
    df_result.loc[needs_update, date_field_a] = df_result.loc[needs_update, '_b_dt'].dt.strftime('%Y-%m-%d')
    df_result.loc[needs_update, source_field] = source_field_value

    updated_count = needs_update.sum()
    print(f"Records actually updated: {updated_count}")
    print(f"=== End Diagnostic Info ===\n")

    # Cleanup
    df_result = df_result.drop(columns=['_a_dt', '_b_dt'])
    return df_result


def diagnose_data_issues(
    csv_file_a: str,
    csv_file_b: str,
    join_field_a: str,
    join_field_b: str,
    date_field_a: str,
    date_field_b: str
):
    """
    Diagnostic function to understand data structure and potential issues.
    
    Parameters
    ----------
    csv_file_a : str
        Path to CSV file A.
    csv_file_b : str
        Path to CSV file B.
    join_field_a : str
        Column name in Table A to join on.
    join_field_b : str
        Column name in Table B to join on.
    date_field_a : str
        Date field name in Table A.
    date_field_b : str
        Date field name in Table B.
    """
    df_a = read_csv_to_dataframe(csv_file_a)
    df_b = read_csv_to_dataframe(csv_file_b)
    
    print("=== TABLE A DIAGNOSTICS ===")
    print(f"Total records: {len(df_a)}")
    print(f"Unique values in {join_field_a}: {df_a[join_field_a].nunique()}")
    print(f"Null values in {join_field_a}: {df_a[join_field_a].isna().sum()}")
    print(f"Null/empty values in {date_field_a}: {df_a[date_field_a].isna().sum()}")
    print(f"\nSample of {date_field_a} values:")
    print(df_a[date_field_a].value_counts().head(10))
    print(f"\nData types:")
    print(df_a[[join_field_a, date_field_a]].dtypes)
    
    print("\n=== TABLE B DIAGNOSTICS ===")
    print(f"Total records: {len(df_b)}")
    print(f"Unique values in {join_field_b}: {df_b[join_field_b].nunique()}")
    print(f"Null values in {join_field_b}: {df_b[join_field_b].isna().sum()}")
    print(f"Null/empty values in {date_field_b}: {df_b[date_field_b].isna().sum()}")
    print(f"\nSample of {date_field_b} values:")
    print(df_b[date_field_b].value_counts().head(10))
    print(f"\nData types:")
    print(df_b[[join_field_b, date_field_b]].dtypes)
    
    print("\n=== JOIN ANALYSIS ===")
    # Check how many values in A have matches in B
    matches = df_a[join_field_a].isin(df_b[join_field_b])
    print(f"Records in A with matching values in B: {matches.sum()}")
    print(f"Records in A without matching values in B: {(~matches).sum()}")
    
    # Check for duplicates in join fields
    print(f"\nDuplicate values in A's {join_field_a}: {df_a[join_field_a].duplicated().sum()}")
    print(f"Duplicate values in B's {join_field_b}: {df_b[join_field_b].duplicated().sum()}")


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
    df_result[source_field_name] = default_value
    return df_result


def process_csv_files(
    csv_file_a: str,
    csv_file_b: str,
    join_field_a: str,
    join_field_b: str,
    date_field_a: str,
    date_field_b: str,
    source_field_name: str,
    source_field_value: str = 'Project Date',
    output_file: Optional[str] = None
) -> pd.DataFrame:
    """
    Main orchestration function to process two CSV files.
    
    Reads two CSV files, joins them, and conditionally updates dates
    from Table B to Table A based on the earliest date per group.
    
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
    date_field_b : str
        Date field name in Table B containing source dates.
    source_field_name : str
        Name for the new field explaining data source.
    source_field_value : str, optional
        Value to be entered into source_field if date is updated.
        Default is 'Project Date'.
    output_file : str, optional
        Path to save the output CSV. If None, file is not saved.
    
    Returns
    -------
    pd.DataFrame
        Processed DataFrame with updated dates and source information.
    
    Examples
    --------
    >>> result = process_csv_files(
    ...     'table_a.csv',
    ...     'table_b.csv',
    ...     'asset_id',
    ...     'asset_id',
    ...     'install_date',
    ...     'project_date',
    ...     'date_source',
    ...     'Project Date'
    ... )
    """
    # Step 1: Read CSV files
    df_a = read_csv_to_dataframe(csv_file_a)
    df_a[join_field_a] = df_a[join_field_a].astype(str).str.strip()
    df_a.loc[df_a[join_field_a].isin(["", "nan", "None"]), join_field_a] = pd.NA
    # TODO - try commenting out the line below if not getting desired results
    df_a[join_field_a] = df_a[join_field_a].str.replace(r"\.0$", "", regex=True)


    df_b = read_csv_to_dataframe(csv_file_b)
    
    print(f"Table A records: {len(df_a)}")
    print(f"Table B records: {len(df_b)}")
    
    # Step 2: Prepare Table B to have only earliest date per join value
    df_b_prepared = prepare_table_b_with_earliest_dates(df_b, join_field_b, date_field_b)
    print(f"Table B after getting earliest dates: {len(df_b_prepared)}")
    
    # Step 3: Join dataframes
    #df_joined = join_dataframes(df_a, df_b_prepared, join_field_a, join_field_b)
    df_joined = df_a.merge(
    df_b_prepared,
    left_on=join_field_a,
    right_on=join_field_b,
    how="left"
    )
    print(f"Joined table records: {len(df_joined)}")
    # TODO - remove if unused - check results for project 5395
    print(df_joined[df_joined['PROJECT'] == '5395'][['PROJECT', 'ASB_DATE', 'EARLIEST_DATE']].head(25))
    
    # Step 4: Add source field
    df_with_source = add_source_field(df_joined, source_field_name)
    
    # Step 5: Update dates conditionally
    df_final = update_dates_conditionally(
        df_with_source,
        date_field_a,
        "EARLIEST_DATE",
        #date_field_b,
        #join_field_a,
        source_field_name,
        source_field_value
    )
    
    # Optional: Save to file
    if output_file:
        df_final.to_csv(output_file, index=False)
        print(f"Results saved to {output_file}")
    
    return df_final


if __name__ == "__main__":
    dirname = os.path.dirname(__file__)
    # update sewer using as-built dates
    csv_file_a = os.path.join(dirname, r'csv\sewer-lines-table-20260106.csv')
    csv_file_b = os.path.join(dirname, r'csv\as-built-project-table-20251217.csv')
    join_field_a = 'PROJECT'
    join_field_b = 'ProjectNumber'
    date_field_a = 'ASB_DATE'
    date_field_b = 'AsBuiltDate'
    source_field_name = 'As_Built_Date_Source'
    source_field_value = 'Project As-Built Date'
    output_file = os.path.join(dirname, r'csv\sewer-lines-table-20260106-updated-with-asbuilt-dates.csv')

    diagnose_data_issues(
        csv_file_a=csv_file_a,
        csv_file_b=csv_file_b,
        join_field_a=join_field_a,
        join_field_b=join_field_b,
        date_field_a=date_field_a,
        date_field_b=date_field_b
    )
        
    result = process_csv_files(
        csv_file_a=csv_file_a,
        csv_file_b=csv_file_b,
        join_field_a=join_field_a,
        join_field_b=join_field_b,
        date_field_a=date_field_a,
        date_field_b=date_field_b,
        source_field_name=source_field_name,
        source_field_value=source_field_value,
        output_file=output_file
    )
    
    print(f"Processed {len(result)} records")
    #print(f"Updated {(result['date_source'] == 'Project Date').sum()} dates")
    print(f"Updated {(result[source_field_name] == source_field_value).sum()} dates")
