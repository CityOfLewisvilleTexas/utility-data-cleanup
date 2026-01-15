import os
from dotenv import load_dotenv
import pathlib
import arcpy

def set_environment():
    """
    Set the environment for the script by loading the .env file and defining arcpy env settings.
    Assumes the .env file is in the same directory as this script.
    """
    script_dir = pathlib.Path(__file__).parent.resolve()
    env_path = script_dir / '.env'
    load_dotenv(dotenv_path=env_path)
    arcpy.env.overwriteOutput = True
    arcpy.env.workspace = os.getenv('GDB')


def add_required_fields(feature_class, field_base_name, field_type, field_length=None):
    """
    Add required adjacent attribute fields to the feature class if they don't already exist.
    Creates 4 fields each for 'from' and 'to' directions.
    :param feature_class: The feature class to check and add fields to.
    :param field_base_name: The base name for the fields (e.g., 'Material', 'ASB_DATE', 'Owner').
    :param field_type: The field type (e.g., 'TEXT', 'DATE', 'SHORT').
    :param field_length: Optional field length for TEXT fields.
    """
    print(f"Checking and adding required fields for {field_base_name}...")

    existing_fields = [f.name for f in arcpy.ListFields(feature_class)]

    # Create field names: From_Material_1, From_Material_2, etc.
    fields_to_add = {}
    for i in range(1, 5):
        from_field = f"From_{field_base_name}_{i}"
        to_field = f"To_{field_base_name}_{i}"
        fields_to_add[from_field] = field_type
        fields_to_add[to_field] = field_type

    for field_name, ftype in fields_to_add.items():
        if field_name not in existing_fields:
            print(f"Adding field: {field_name} ({ftype})")
            if ftype == "TEXT" and field_length:
                arcpy.AddField_management(feature_class, field_name, ftype, field_length=field_length)
            else:
                arcpy.AddField_management(feature_class, field_name, ftype)
        else:
            print(f"Field '{field_name}' already exists.")


def calculate_adjacent_attributes(feature_class, id_field, source_field, value_map=None):
    """
    Read the feature attributes and look up values from adjacent segments.
    Expects the feature class to already have from_adjacent_id_1-4 and to_adjacent_id_1-4 fields.
    :param feature_class: Path of the feature class to read from.
    :param id_field: The name of the unique ID field in the feature class.
    :param source_field: The field containing the source attribute to propagate.
    :param value_map: Optional dictionary to map source field values. If None, values are copied directly.
    :return: Dictionary keyed by OID with values for from and to attributes (1-4).
    """
    print(f"Reading feature attributes and calculating adjacency for '{source_field}'...")

    # First pass: build a lookup dictionary of all features by their ID
    id_to_value = {}
    fields_to_read = ['OID@', id_field, source_field]
    
    with arcpy.da.SearchCursor(feature_class, fields_to_read) as cursor:
        for row in cursor:
            oid, feat_id, source_value = row
            id_to_value[feat_id] = source_value

    print(f"Built lookup table with {len(id_to_value)} features.")

    # Second pass: read adjacent IDs and look up their values
    results = {}
    
    adjacent_fields = ['OID@']
    for i in range(1, 5):
        adjacent_fields.append(f'from_adjacent_id_{i}')
    for i in range(1, 5):
        adjacent_fields.append(f'to_adjacent_id_{i}')
    
    with arcpy.da.SearchCursor(feature_class, adjacent_fields) as cursor:
        for row in cursor:
            oid = row[0]
            
            # Get from_adjacent values (indices 1-4 in row)
            from_values = []
            for i in range(1, 5):
                adj_id = row[i]
                if adj_id is not None and adj_id in id_to_value:
                    source_val = id_to_value[adj_id]
                    if value_map is not None:
                        mapped_val = value_map.get(source_val, "Unknown")
                    else:
                        mapped_val = source_val
                    from_values.append(mapped_val)
                else:
                    from_values.append(None)
            
            # Get to_adjacent values (indices 5-8 in row)
            to_values = []
            for i in range(5, 9):
                adj_id = row[i]
                if adj_id is not None and adj_id in id_to_value:
                    source_val = id_to_value[adj_id]
                    if value_map is not None:
                        mapped_val = value_map.get(source_val, "Unknown")
                    else:
                        mapped_val = source_val
                    to_values.append(mapped_val)
                else:
                    to_values.append(None)
            
            results[oid] = {
                'from_values': from_values,
                'to_values': to_values
            }

    print(f"Finished calculating adjacency for '{source_field}'.")
    return results


def update_fields(feature_class, calc_dict, field_base_name):
    """
    Update the fields in the feature class with the calculated values.
    :param feature_class: The feature class to update.
    :param calc_dict: Dictionary keyed by OID with calculated values.
    :param field_base_name: The base name for the fields (e.g., 'Material', 'ASB_DATE').
    """
    print("Updating fields in the feature class...")
    
    update_fields_list = ['OID@']
    for i in range(1, 5):
        update_fields_list.append(f"From_{field_base_name}_{i}")
    for i in range(1, 5):
        update_fields_list.append(f"To_{field_base_name}_{i}")

    desc = arcpy.Describe(feature_class)
    editor = arcpy.da.Editor(desc.path)

    try:
        if not editor.isEditing:
            editor.startEditing(False, False)
        editor.startOperation()

        with arcpy.da.UpdateCursor(feature_class, update_fields_list) as cursor:
            for row in cursor:
                oid = row[0]
                data = calc_dict.get(oid)

                if data:
                    # Update from values (indices 1-4)
                    for i in range(4):
                        row[i + 1] = data['from_values'][i]
                    
                    # Update to values (indices 5-8)
                    for i in range(4):
                        row[i + 5] = data['to_values'][i]
                else:
                    # Set all to None if no data
                    for idx in range(1, len(update_fields_list)):
                        row[idx] = None

                cursor.updateRow(row)

        editor.stopOperation()
        editor.stopEditing(True)
        print("Attribute table updated successfully with adjacency fields.")
    except Exception as e:
        print(f"Error during attribute table update: {e}")
        if editor.isEditing:
            editor.stopOperation()
            editor.stopEditing(False)


def run():
    set_environment()

    input_fc_name = os.getenv('INPUT_FC')
    input_fc = os.path.join(arcpy.env.workspace, input_fc_name)

    # Check if input feature class already has adjacent ID fields
    existing_fields = [f.name for f in arcpy.ListFields(input_fc)]
    required_adjacent_fields = [f'from_adjacent_id_{i}' for i in range(1, 5)] + \
                               [f'to_adjacent_id_{i}' for i in range(1, 5)]
    
    missing_fields = [f for f in required_adjacent_fields if f not in existing_fields]
    
    if missing_fields:
        print(f"ERROR: Input feature class is missing required adjacent ID fields:")
        for field in missing_fields:
            print(f"  - {field}")
        print("\nPlease run get_flow_direction.py first to create these fields.")
        return

    # Configuration: Set which attribute to propagate
    attribute_mode = os.getenv('ATTRIBUTE_MODE', 'DATE').upper()
    id_field_name = "FACILITYID"

    if attribute_mode == 'MATERIAL':
        source_field = "PIPE_TYPE"
        field_base_name = "Material"
        field_type = "SHORT"
        field_length = None
        
        # Optional: Define a value map if you want to convert codes to text
        # value_map = {
        #     1: "PVC",
        #     2: "RCP",
        #     3: "Cast Iron",
        #     4: "Ductile Iron",
        #     5: "VCP",
        #     6: "R.C.C.P",
        #     None: "Unknown",
        #     0: "Unknown"
        # }
        # If using value map, change field_type to "TEXT" and set field_length = 50
        value_map = None

    elif attribute_mode == 'OWNER':
        source_field = "OWNER"
        field_base_name = "Owner"
        field_type = "SHORT"
        field_length = None
        value_map = None
    
    elif attribute_mode == 'DATE':
        source_field = "ASB_DATE"
        field_base_name = "ASB_DATE"
        field_type = "DATE"
        field_length = None
        value_map = None

    else:
        print(f"Unknown ATTRIBUTE_MODE: {attribute_mode}. Use 'MATERIAL', 'DATE', or 'OWNER'.")
        return

    add_required_fields(input_fc, field_base_name, field_type, field_length)
    calc_results = calculate_adjacent_attributes(input_fc, id_field_name, source_field, value_map)
    update_fields(input_fc, calc_results, field_base_name)

    print(f"\nScript finished for {attribute_mode} mode.")


if __name__ == "__main__":
    run()