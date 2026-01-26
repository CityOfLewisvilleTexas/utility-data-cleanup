import os
import sys
from dotenv import load_dotenv
import pathlib
import arcpy


class DualLogger:
    """
    Logger that writes to both console and file.
    """
    def __init__(self, log_file_path):
        self.terminal = sys.stdout
        self.log_file = open(log_file_path, 'x')
    
    def write(self, message):
        self.terminal.write(message)
        self.log_file.write(message)
    
    def flush(self):
        self.terminal.flush()
        self.log_file.flush()
    
    def close(self):
        self.log_file.close()


def set_environment(env_path):
    """
    Set the environment for the script by loading the .env file and defining arcpy env settings.
    """
    load_dotenv(dotenv_path=env_path)
    arcpy.env.overwriteOutput = True
    arcpy.env.workspace = os.getenv('GDB')


def add_source_fields(feature_class):
    """
    Add source tracking fields if they don't exist.
    """
    print("Checking and adding source tracking fields...")
    existing_fields = [f.name for f in arcpy.ListFields(feature_class)]
    
    fields_to_add = {
        'As_Built_Date_Source': ('TEXT', 100),
        'Pipe_Type_Source': ('TEXT', 100)
    }
    
    for field_name, (field_type, field_length) in fields_to_add.items():
        if field_name not in existing_fields:
            print(f"Adding field: {field_name}")
            arcpy.AddField_management(feature_class, field_name, field_type, field_length=field_length)
        else:
            print(f"Field '{field_name}' already exists.")


def reset_field_values(input_fc: str, fields: list):
    """
    Set values of fields in given feature class to null
    
    :param input_fc: name of input feature class
    :param fields: list of strings containing field names
    """
    for field in fields:
        arcpy.management.CalculateField(input_fc, field, 'None', "PYTHON3")
    print(f"All values in the following fields were set to null: {fields}")


def get_non_null_values(values_list):
    """
    Get non-null values from a list and return unique non-null values.
    """
    non_null = [v for v in values_list if v is not None]
    return non_null


def get_city_owned_values(owner_values, attribute_values):
    """
    Extract attribute values only from city-owned (Owner=1) segments.
    Returns a list of attribute values where the corresponding owner is 1.
    """
    city_values = []
    for owner, attr_val in zip(owner_values, attribute_values):
        if owner == 1 and attr_val is not None:
            city_values.append(attr_val)
    return city_values


def check_can_assign(owner_values, attribute_values):
    """
    Check if we can assign a value based on city-owned segments.
    Returns: (can_assign, value_to_assign, reason)
    
    Logic:
    - Extract values only from segments where Owner=1
    - If no city-owned segments exist, cannot assign
    - If city-owned segments have conflicting values, cannot assign
    - If all city-owned segments have the same value, can assign that value
    """
    city_values = get_city_owned_values(owner_values, attribute_values)
    
    if not city_values:
        # No city-owned segments with values
        return (False, None, "no_city_owned")
    
    unique_city_values = list(set(city_values))
    
    if len(unique_city_values) == 1:
        # All city-owned segments agree on one value
        return (True, unique_city_values[0], "city_owned_agree")
    else:
        # City-owned segments have conflicting values
        return (False, None, "city_owned_conflict")


def has_conflicting_values(values_list):
    """
    Check if there are conflicting non-null values in the list.
    Returns True only if there are 2+ different non-null values.
    Returns False if all null or only one unique value.
    """
    non_null = [v for v in values_list if v is not None]
    unique_values = list(set(non_null))
    return len(unique_values) > 1


def process_assignments(feature_class, adjacency_round):
    """
    Process the feature class to assign missing ASB_DATE and PIPE_TYPE values
    based on adjacent segment data.
    """
    print(f"Processing assignments for Round {adjacency_round}...")
    
    # Define all fields needed
    fields_list = [
        'OID@', 'FACILITYID', 'ASB_DATE', 'PIPE_TYPE',
        'As_Built_Date_Source', 'Pipe_Type_Source',
        # To fields
        'To_Owner_1', 'To_Owner_2', 'To_Owner_3', 'To_Owner_4',
        'To_ASB_DATE_1', 'To_ASB_DATE_2', 'To_ASB_DATE_3', 'To_ASB_DATE_4',
        'To_Material_1', 'To_Material_2', 'To_Material_3', 'To_Material_4',
        # From fields
        'From_Owner_1', 'From_Owner_2', 'From_Owner_3', 'From_Owner_4',
        'From_ASB_DATE_1', 'From_ASB_DATE_2', 'From_ASB_DATE_3', 'From_ASB_DATE_4',
        'From_Material_1', 'From_Material_2', 'From_Material_3', 'From_Material_4'
    ]
    
    desc = arcpy.Describe(feature_class)
    editor = arcpy.da.Editor(desc.path)
    
    stats = {
        'total_processed': 0,
        'date_assigned_to': 0,
        'date_assigned_from': 0,
        'material_assigned_to': 0,
        'material_assigned_from': 0,
        'skipped_date_to': 0,
        'skipped_date_from': 0,
        'skipped_material_to': 0,
        'skipped_material_from': 0
    }
    
    try:
        if not editor.isEditing:
            editor.startEditing(False, False)
        editor.startOperation()
        
        with arcpy.da.UpdateCursor(feature_class, fields_list) as cursor:
            for row in cursor:
                oid = row[0]
                facility_id = row[1]
                asb_date = row[2]
                pipe_type = row[3]
                date_source = row[4]
                material_source = row[5]
                
                # Extract To values
                to_owners = [row[6], row[7], row[8], row[9]]
                to_dates = [row[10], row[11], row[12], row[13]]
                to_materials = [row[14], row[15], row[16], row[17]]
                
                # Extract From values
                from_owners = [row[18], row[19], row[20], row[21]]
                from_dates = [row[22], row[23], row[24], row[25]]
                from_materials = [row[26], row[27], row[28], row[29]]
                
                updated = False
                
                # Process ASB_DATE using To fields
                if asb_date is None:
                    can_assign, date_value, reason = check_can_assign(to_owners, to_dates)
                    
                    if can_assign:
                        row[2] = date_value  # ASB_DATE
                        row[4] = f'Adjacency To-As-Built-Date (Round {adjacency_round})'  # As_Built_Date_Source
                        stats['date_assigned_to'] += 1
                        updated = True
                    elif reason == "city_owned_conflict":
                        # City-owned segments have conflicting dates
                        stats['skipped_date_to'] += 1
                        city_dates = get_city_owned_values(to_owners, to_dates)
                        print(f"SKIP DATE (To): FACILITYID={facility_id}, City-owned segments have conflicting dates. To_Owners={to_owners}, To_Dates={to_dates}, City_Dates={city_dates}")
                
                # Process PIPE_TYPE using To fields
                if pipe_type is None:
                    can_assign, material_value, reason = check_can_assign(to_owners, to_materials)
                    
                    if can_assign:
                        row[3] = material_value  # PIPE_TYPE
                        row[5] = f'Adjacency To-Material (Round {adjacency_round})'  # Pipe_Type_Source
                        stats['material_assigned_to'] += 1
                        updated = True
                    elif reason == "city_owned_conflict":
                        # City-owned segments have conflicting materials
                        stats['skipped_material_to'] += 1
                        city_materials = get_city_owned_values(to_owners, to_materials)
                        print(f"SKIP MATERIAL (To): FACILITYID={facility_id}, City-owned segments have conflicting materials. To_Owners={to_owners}, To_Materials={to_materials}, City_Materials={city_materials}")
                
                # Process ASB_DATE using From fields (if still null)
                if row[2] is None:  # Check current value in row, may have been updated above
                    can_assign, date_value, reason = check_can_assign(from_owners, from_dates)
                    
                    if can_assign:
                        row[2] = date_value  # ASB_DATE
                        row[4] = f'Adjacency From-As-Built-Date (Round {adjacency_round})'  # As_Built_Date_Source
                        stats['date_assigned_from'] += 1
                        updated = True
                    elif reason == "city_owned_conflict":
                        # City-owned segments have conflicting dates
                        stats['skipped_date_from'] += 1
                        city_dates = get_city_owned_values(from_owners, from_dates)
                        print(f"SKIP DATE (From): FACILITYID={facility_id}, City-owned segments have conflicting dates. From_Owners={from_owners}, From_Dates={from_dates}, City_Dates={city_dates}")
                
                # Process PIPE_TYPE using From fields (if still null)
                if row[3] is None:  # Check current value in row
                    can_assign, material_value, reason = check_can_assign(from_owners, from_materials)
                    
                    if can_assign:
                        row[3] = material_value  # PIPE_TYPE
                        row[5] = f'Adjacency From-Material (Round {adjacency_round})'  # Pipe_Type_Source
                        stats['material_assigned_from'] += 1
                        updated = True
                    elif reason == "city_owned_conflict":
                        # City-owned segments have conflicting materials
                        stats['skipped_material_from'] += 1
                        city_materials = get_city_owned_values(from_owners, from_materials)
                        print(f"SKIP MATERIAL (From): FACILITYID={facility_id}, City-owned segments have conflicting materials. From_Owners={from_owners}, From_Materials={from_materials}, City_Materials={city_materials}")
                
                if updated:
                    cursor.updateRow(row)
                
                stats['total_processed'] += 1
        
        editor.stopOperation()
        editor.stopEditing(True)
        print("\nAssignment completed successfully.")
        
    except Exception as e:
        print(f"Error during processing: {e}")
        if editor.isEditing:
            editor.stopOperation()
            editor.stopEditing(False)
    
    return stats


def print_statistics(stats):
    """
    Print summary statistics of the assignment process.
    """
    print("\n" + "="*60)
    print("ASSIGNMENT STATISTICS")
    print("="*60)
    print(f"Total features processed: {stats['total_processed']}")
    print(f"\nDates assigned from To fields: {stats['date_assigned_to']}")
    print(f"Dates assigned from From fields: {stats['date_assigned_from']}")
    print(f"Dates skipped (To): {stats['skipped_date_to']}")
    print(f"Dates skipped (From): {stats['skipped_date_from']}")
    print(f"\nMaterials assigned from To fields: {stats['material_assigned_to']}")
    print(f"Materials assigned from From fields: {stats['material_assigned_from']}")
    print(f"Materials skipped (To): {stats['skipped_material_to']}")
    print(f"Materials skipped (From): {stats['skipped_material_from']}")
    print("="*60)


def run():
    script_dir = pathlib.Path(__file__).parent.resolve()
    env_path = script_dir / '.env'
    set_environment(env_path)
    
    input_fc_name = os.getenv('INPUT_FC')
    input_fc = os.path.join(arcpy.env.workspace, input_fc_name)
    
    adjacency_round = int(os.getenv('ADJACENCY_ROUND', 1))
    log_file_path = os.path.join(script_dir, os.getenv('LOG_FILE'))
    
    if not log_file_path:
        print("ERROR: LOG_FILE environment variable not set in .env file")
        return
    
    #TODO - move to separate function and/or file?
    if os.path.isfile(log_file_path):
        try:
            os.remove(log_file_path)
        except OSError:
            pass

    # Set up dual logging
    logger = DualLogger(log_file_path)
    sys.stdout = logger
    
    try:
        print(f"Processing feature class: {input_fc}")
        print(f"Adjacency round: {adjacency_round}")
        print(f"Log file: {log_file_path}")
        print("="*60)
        
        # Verify required fields exist
        existing_fields = [f.name for f in arcpy.ListFields(input_fc)]
        required_source_fields = [
            'FACILITYID', 'ASB_DATE', 'PIPE_TYPE', 'To_Owner_1', 'To_Owner_2', 'To_Owner_3', 'To_Owner_4'
        ]
        required_output_fields = [
            'To_ASB_DATE_1', 'To_ASB_DATE_2', 'To_ASB_DATE_3', 'To_ASB_DATE_4',
            'To_Material_1', 'To_Material_2', 'To_Material_3', 'To_Material_4',
            'From_Owner_1', 'From_Owner_2', 'From_Owner_3', 'From_Owner_4',
            'From_ASB_DATE_1', 'From_ASB_DATE_2', 'From_ASB_DATE_3', 'From_ASB_DATE_4',
            'From_Material_1', 'From_Material_2', 'From_Material_3', 'From_Material_4']
        
        required_fields = required_source_fields + required_output_fields
        
        missing_fields = [f for f in required_fields if f not in existing_fields]
        
        if missing_fields:
            print(f"ERROR: Input feature class is missing required fields:")
            for field in missing_fields:
                print(f"  - {field}")
            print("\nPlease run obtain_adjacent_values.py first for both OWNER, DATE, and MATERIAL modes.")
            return
        
        # no fields should be reset here
        #reset_field_values(input_fc, required_output_fields)
        add_source_fields(input_fc)
        stats = process_assignments(input_fc, adjacency_round)
        print_statistics(stats)
        
        print(f"\nScript finished for Round {adjacency_round}.")
        
    finally:
        # Restore stdout and close log file
        sys.stdout = logger.terminal
        logger.close()
        print(f"Log written to: {log_file_path}")


if __name__ == "__main__":
    run()