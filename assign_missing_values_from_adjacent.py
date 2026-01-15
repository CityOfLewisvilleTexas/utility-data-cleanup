import os
from dotenv import load_dotenv
import pathlib
import arcpy


def set_environment():
    """
    Set the environment for the script by loading the .env file and defining arcpy env settings.
    """
    script_dir = pathlib.Path(__file__).parent.resolve()
    env_path = script_dir / '.env'
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


def get_non_null_values(values_list):
    """
    Get non-null values from a list and return unique non-null values.
    """
    non_null = [v for v in values_list if v is not None]
    return non_null


def check_all_owner_equal_one(owner_values):
    """
    Check if all owner values are 1 (null values are ignored).
    """
    non_null_owners = [v for v in owner_values if v is not None]
    if not non_null_owners:
        return False
    return all(v == 1 for v in non_null_owners)


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
                    if check_all_owner_equal_one(to_owners):
                        non_null_dates = get_non_null_values(to_dates)
                        unique_dates = list(set(non_null_dates))
                        
                        if len(unique_dates) == 1:
                            row[2] = unique_dates[0]  # ASB_DATE
                            row[4] = f'Adjacency To-As-Built-Date (Round {adjacency_round})'  # As_Built_Date_Source
                            stats['date_assigned_to'] += 1
                            updated = True
                        elif len(unique_dates) > 1 or len(unique_dates) == 0:
                            stats['skipped_date_to'] += 1
                            print(f"SKIP DATE (To): FACILITYID={facility_id}, To_Owners={to_owners}, To_Dates={to_dates}, To_Materials={to_materials}")
                    else:
                        stats['skipped_date_to'] += 1
                        print(f"SKIP DATE (To): FACILITYID={facility_id}, To_Owners={to_owners}, To_Dates={to_dates}, To_Materials={to_materials}")
                
                # Process PIPE_TYPE using To fields
                if pipe_type is None:
                    if check_all_owner_equal_one(to_owners):
                        non_null_materials = get_non_null_values(to_materials)
                        unique_materials = list(set(non_null_materials))
                        
                        if len(unique_materials) == 1:
                            row[3] = unique_materials[0]  # PIPE_TYPE
                            row[5] = f'Adjacency To-Material (Round {adjacency_round})'  # Pipe_Type_Source
                            stats['material_assigned_to'] += 1
                            updated = True
                        elif len(unique_materials) > 1 or len(unique_materials) == 0:
                            stats['skipped_material_to'] += 1
                            print(f"SKIP MATERIAL (To): FACILITYID={facility_id}, To_Owners={to_owners}, To_Dates={to_dates}, To_Materials={to_materials}")
                    else:
                        stats['skipped_material_to'] += 1
                        print(f"SKIP MATERIAL (To): FACILITYID={facility_id}, To_Owners={to_owners}, To_Dates={to_dates}, To_Materials={to_materials}")
                
                # Process ASB_DATE using From fields (if still null)
                if row[2] is None:  # Check current value in row, may have been updated above
                    if check_all_owner_equal_one(from_owners):
                        non_null_dates = get_non_null_values(from_dates)
                        unique_dates = list(set(non_null_dates))
                        
                        if len(unique_dates) == 1:
                            row[2] = unique_dates[0]  # ASB_DATE
                            row[4] = f'Adjacency From-As-Built-Date (Round {adjacency_round})'  # As_Built_Date_Source
                            stats['date_assigned_from'] += 1
                            updated = True
                        elif len(unique_dates) > 1 or len(unique_dates) == 0:
                            stats['skipped_date_from'] += 1
                            print(f"SKIP DATE (From): FACILITYID={facility_id}, From_Owners={from_owners}, From_Dates={from_dates}, From_Materials={from_materials}")
                    else:
                        stats['skipped_date_from'] += 1
                        print(f"SKIP DATE (From): FACILITYID={facility_id}, From_Owners={from_owners}, From_Dates={from_dates}, From_Materials={from_materials}")
                
                # Process PIPE_TYPE using From fields (if still null)
                if row[3] is None:  # Check current value in row
                    if check_all_owner_equal_one(from_owners):
                        non_null_materials = get_non_null_values(from_materials)
                        unique_materials = list(set(non_null_materials))
                        
                        if len(unique_materials) == 1:
                            row[3] = unique_materials[0]  # PIPE_TYPE
                            row[5] = f'Adjacency From-Material (Round {adjacency_round})'  # Pipe_Type_Source
                            stats['material_assigned_from'] += 1
                            updated = True
                        elif len(unique_materials) > 1 or len(unique_materials) == 0:
                            stats['skipped_material_from'] += 1
                            print(f"SKIP MATERIAL (From): FACILITYID={facility_id}, From_Owners={from_owners}, From_Dates={from_dates}, From_Materials={from_materials}")
                    else:
                        stats['skipped_material_from'] += 1
                        print(f"SKIP MATERIAL (From): FACILITYID={facility_id}, From_Owners={from_owners}, From_Dates={from_dates}, From_Materials={from_materials}")
                
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
    set_environment()
    
    input_fc_name = os.getenv('INPUT_FC')
    input_fc = os.path.join(arcpy.env.workspace, input_fc_name)
    
    adjacency_round = int(os.getenv('ADJACENCY_ROUND', 1))
    
    print(f"Processing feature class: {input_fc}")
    print(f"Adjacency round: {adjacency_round}")
    
    # Verify required fields exist
    existing_fields = [f.name for f in arcpy.ListFields(input_fc)]
    required_fields = [
        'FACILITYID', 'ASB_DATE', 'PIPE_TYPE',
        'To_Owner_1', 'To_Owner_2', 'To_Owner_3', 'To_Owner_4',
        'To_ASB_DATE_1', 'To_ASB_DATE_2', 'To_ASB_DATE_3', 'To_ASB_DATE_4',
        'To_Material_1', 'To_Material_2', 'To_Material_3', 'To_Material_4',
        'From_Owner_1', 'From_Owner_2', 'From_Owner_3', 'From_Owner_4',
        'From_ASB_DATE_1', 'From_ASB_DATE_2', 'From_ASB_DATE_3', 'From_ASB_DATE_4',
        'From_Material_1', 'From_Material_2', 'From_Material_3', 'From_Material_4'
    ]
    
    missing_fields = [f for f in required_fields if f not in existing_fields]
    
    if missing_fields:
        print(f"ERROR: Input feature class is missing required fields:")
        for field in missing_fields:
            print(f"  - {field}")
        print("\nPlease run obtain_adjacent_values.py first for both OWNER, DATE, and MATERIAL modes.")
        return
    
    add_source_fields(input_fc)
    stats = process_assignments(input_fc, adjacency_round)
    print_statistics(stats)
    
    print(f"\nScript finished for Round {adjacency_round}.")


if __name__ == "__main__":
    run()