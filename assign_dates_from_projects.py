import os
import pandas as pd
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


def prepare_table_b_with_earliest_dates(
    df_b: pd.DataFrame,
    join_field_b: str,
    date_field_b: str
) -> pd.DataFrame:
    """
    Prepare Table B by getting only the earliest date for each unique join value.
    
    This ensures a true one-to-many relationship by reducing Table B to 
    one record per unique join field value, containing the earliest date.
    
    Parameters
    ----------
    df_b : pd.DataFrame
        Table B with potentially multiple records per join value.
    join_field_b : str
        Column name to group by.
    date_field_b : str
        Column name containing dates to find minimum of.
    
    Returns
    -------
    pd.DataFrame
        Table B reduced to one row per unique join value with earliest date.
    """
    df_b_copy = df_b.copy()
    
    # Convert date field to datetime
    df_b_copy[date_field_b] = pd.to_datetime(df_b_copy[date_field_b], errors='coerce')
    
    # Group by join field and get the row with the earliest date for each group
    idx = df_b_copy.groupby(join_field_b)[date_field_b].idxmin()
    
    # Remove NaN indices (groups where all dates were invalid/null)
    idx = idx.dropna()
    
    # Return only those rows (one per unique join value)
    df_b_earliest = df_b_copy.loc[idx].reset_index(drop=True)
    
    return df_b_earliest


def update_dates_conditionally(
    df: pd.DataFrame,
    date_field_a: str,
    date_field_b: str,
    source_field: str,
    source_field_value: str
) -> pd.DataFrame:
    """
    Update date field in Table A with dates from Table B.
    
    Updates the date field from Table A with dates from Table B,
    but only if the Table A field doesn't already contain a valid value.
    Also updates the source field when a date is written.
    
    Parameters
    ----------
    df : pd.DataFrame
        Joined DataFrame containing data from both tables.
    date_field_a : str
        Column name for the date field in Table A to be updated.
    date_field_b : str
        Column name for the date field from Table B.
    source_field : str
        Column name for the source explanation field.
    source_field_value : str
        Value to be entered into source_field if date is updated.
    
    Returns
    -------
    pd.DataFrame
        DataFrame with conditionally updated dates and source information.
    """
    df_result = df.copy()
    
    # Convert date fields to datetime
    df_result[date_field_a] = pd.to_datetime(df_result[date_field_a], errors='coerce')
    df_result[date_field_b] = pd.to_datetime(df_result[date_field_b], errors='coerce')
    
    # Create a mask for records where:
    # 1. date_field_a is null/invalid AND
    # 2. date_field_b has a valid value
    needs_update = df_result[date_field_a].isna() & df_result[date_field_b].notna()
    
    # Update dates where needed
    df_result.loc[needs_update, date_field_a] = df_result.loc[needs_update, date_field_b]
    
    # Update source field where dates were updated
    df_result.loc[needs_update, source_field] = 'Project Date'
    
    return df_result


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
    source_field_value: str,
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
    source_field_value : str
        Value to be entered into source_field if date is updated.
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
    ...     'date_source'
    ... )
    """
    # Step 1: Read CSV files
    df_a = read_csv_to_dataframe(csv_file_a)
    df_b = read_csv_to_dataframe(csv_file_b)
    
    print(f"Table A records: {len(df_a)}")
    print(f"Table B records: {len(df_b)}")
    
    # Step 2: Prepare Table B to have only earliest date per join value
    df_b_prepared = prepare_table_b_with_earliest_dates(df_b, join_field_b, date_field_b)
    print(f"Table B after getting earliest dates: {len(df_b_prepared)}")
    
    # Step 3: Join dataframes
    df_joined = join_dataframes(df_a, df_b_prepared, join_field_a, join_field_b)
    print(f"Joined table records: {len(df_joined)}")
    
    # Step 4: Add source field
    df_with_source = add_source_field(df_joined, source_field_name)
    
    # Step 5: Update dates conditionally
    df_final = update_dates_conditionally(
        df_with_source,
        date_field_a,
        date_field_b,
        source_field_name,
        source_field_value
    )
    
    # Optional: Save to file
    if output_file:
        df_final.to_csv(output_file, index=False)
        print(f"Results saved to {output_file}")
    
    return df_final


if __name__ == "__main__":
    # Example usage
    dirname = os.path.dirname(__file__)
    csv_file_a = os.path.join(dirname, r'csv\sewer-lines-table-20260106.csv')
    csv_file_b = os.path.join(dirname, r'csv\as-built-project-table-20251217.csv')
    source_field_name = 'As_Built_Date_Source',
    source_field_value = 'Project As-Built Date'
    output_file = os.path.join(dirname, r'csv\sewer-lines-table-20260106-updated.csv')
    result = process_csv_files(
        csv_file_a=csv_file_a,
        csv_file_b=csv_file_b,
        join_field_a='PROJECT',
        join_field_b='ProjectNumber',
        date_field_a='ASB_DATE',
        date_field_b='AsBuiltDate',
        source_field_name=source_field_name,
        source_field_value=source_field_value,
        output_file=output_file
    )
    
    print(f"Processed {len(result)} records")
    #print(f"Updated {(result['date_source'] == 'Project Date').sum()} dates")
    print(f"Updated {(result[source_field_name] == 'Project Date').sum()} dates")



##########NEW functions###############