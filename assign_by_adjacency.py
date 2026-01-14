import os
import math
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


def get_projected_feature_class(in_fc, out_fc, out_coordinate_system, geographic_transformation):
    """
    Project a feature class using the geographic coordinate system WGS84 to a specified coordinate system
    using the given transformation.
    :param in_fc: Path to the input feature class.
    :param out_fc: Path to the output feature class.
    :param out_coordinate_system: The output coordinate system (SpatialReference object).
    :param geographic_transformation: The geographic transformation to use.
    :return: output feature class path
    """
    try:
        arcpy.management.Project(
            in_dataset=in_fc,
            out_dataset=out_fc,
            out_coor_system=out_coordinate_system,
            transform_method=geographic_transformation,
            in_coor_system=arcpy.SpatialReference(4326)
        )
        print("Projection complete.")
        return out_fc

    except Exception as e:
        print(f"Error during projection: {e}")
        exit()


def add_required_fields(feature_class, from_field, to_field, field_type, field_length=None):
    """
    Add required adjacent attribute fields to the feature class if they don't already exist.
    Assumes 'from_adjacent_id' and 'to_adjacent_id' already exist.
    :param feature_class: The projected feature class to check and add fields to.
    :param from_field: The name of the field for the attribute at the start point.
    :param to_field: The name of the field for the attribute at the end point.
    :param field_type: The field type (e.g., 'TEXT', 'DATE').
    :param field_length: Optional field length for TEXT fields.
    """
    print(f"Checking and adding required fields on the projected feature class...")

    existing_fields = [f.name for f in arcpy.ListFields(feature_class)]

    fields_to_add = {
        from_field: field_type,
        to_field: field_type
    }

    for field_name, ftype in fields_to_add.items():
        if field_name not in existing_fields:
            print(f"Adding field: {field_name} ({ftype})")
            if ftype == "TEXT" and field_length:
                arcpy.AddField_management(feature_class, field_name, ftype, field_length=field_length)
            else:
                arcpy.AddField_management(feature_class, field_name, ftype)
        else:
            print(f"Field '{field_name}' already exists.")


def calculate_adjacent_attributes(feature_class, id_field, source_field, xy_tolerance, value_map=None):
    """
    Read the feature geometries from the feature class and calculate adjacent IDs and attribute values for each segment.
    :param feature_class: Path of the projected feature class to read from.
    :param id_field: The name of the unique ID field in the feature class.
    :param source_field: The field containing the source attribute to propagate.
    :param xy_tolerance: Tolerance for comparing point locations in the projected coordinate system units.
    :param value_map: Optional dictionary to map source field values (e.g., for materials). If None, values are copied directly.
    :return: Dictionary keyed by OID with values:
             { 'from_adjacent_id': ..., 'to_adjacent_id': ..., 'from_value': ..., 'to_value': ... }
    """
    print(f"Reading projected feature geometries and calculating adjacency for '{source_field}'...")

    # First pass: read geometries & attributes
    features_data = {}
    fields_to_read = ['OID@', id_field, 'SHAPE@', source_field]
    with arcpy.da.SearchCursor(feature_class, fields_to_read) as cursor:
        for row in cursor:
            oid, feat_id, shape, source_value = row
            if shape is None:
                continue
            try:
                start_pt = shape.firstPoint
                end_pt = shape.lastPoint
                sx, sy = start_pt.X, start_pt.Y
                ex, ey = end_pt.X, end_pt.Y
            except:
                continue
            features_data[oid] = {
                'id': feat_id,
                'sx': sx, 'sy': sy,
                'ex': ex, 'ey': ey,
                'source_value': source_value
            }

    print(f"Read and processed {len(features_data)} features.")

    # Build endpoint list for adjacency lookup
    endpoints = []
    for oid, data in features_data.items():
        endpoints.append({'oid': oid, 'x': data['sx'], 'y': data['sy']})
        endpoints.append({'oid': oid, 'x': data['ex'], 'y': data['ey']})

    # Prepare output dictionary
    results = {}

    # Second pass: calculate adjacency and values
    for i, (oid, data) in enumerate(features_data.items()):
        sx, sy = data['sx'], data['sy']
        ex, ey = data['ex'], data['ey']

        from_adj = None
        to_adj = None
        from_val = None
        to_val = None

        # Find from_adjacent_id/value
        for ep in endpoints:
            if ep['oid'] == oid:
                continue
            if math.dist((sx, sy), (ep['x'], ep['y'])) < xy_tolerance:
                from_adj = features_data[ep['oid']]['id']
                adj_source = features_data[ep['oid']]['source_value']
                if value_map is not None:
                    from_val = value_map.get(adj_source, "Unknown")
                else:
                    from_val = adj_source
                break

        # Find to_adjacent_id/value
        for ep in endpoints:
            if ep['oid'] == oid:
                continue
            if math.dist((ex, ey), (ep['x'], ep['y'])) < xy_tolerance:
                to_adj = features_data[ep['oid']]['id']
                adj_source = features_data[ep['oid']]['source_value']
                if value_map is not None:
                    to_val = value_map.get(adj_source, "Unknown")
                else:
                    to_val = adj_source
                break

        results[oid] = {
            'from_adjacent_id': from_adj,
            'to_adjacent_id': to_adj,
            'from_value': from_val,
            'to_value': to_val
        }

        if (i + 1) % 1000 == 0:
            print(f"Processed {i + 1} features for adjacency...")

    print(f"Finished calculating adjacency for '{source_field}'.")
    return results


def update_fields(feature_class, calc_dict, from_adj_field, to_adj_field, from_value_field, to_value_field):
    """
    Update the fields in the feature class with the calculated values.
    :param feature_class: The feature class to update.
    :param calc_dict: Dictionary keyed by OID with calculated values.
    :param from_adj_field: The field name for the start-point adjacent ID.
    :param to_adj_field: The field name for the end-point adjacent ID.
    :param from_value_field: The field name for the start-point value.
    :param to_value_field: The field name for the end-point value.
    """
    print("Updating fields in the feature class...")
    update_fields_list = [
        'OID@',
        from_adj_field, to_adj_field,
        from_value_field, to_value_field
    ]

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
                    row[1] = data['from_adjacent_id']
                    row[2] = data['to_adjacent_id']
                    row[3] = data['from_value']
                    row[4] = data['to_value']
                else:
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

    spatial_ref_wkid = int(os.getenv('SPATIAL_REF_WKID', 2277))
    out_coordinate_system = arcpy.SpatialReference(spatial_ref_wkid)
    geographic_transformation = os.getenv('GEOGRAPHIC_TRANSFORMATION', "WGS_1984_(ITRF00)_To_NAD_1983")

    output_fc_name = f"{input_fc_name}_{spatial_ref_wkid}"
    projected_fc = get_projected_feature_class(input_fc, output_fc_name,
                                               out_coordinate_system, geographic_transformation)

    # Configuration: Set which attribute to propagate
    # Options: 'MATERIAL' or 'DATE'
    attribute_mode = os.getenv('ATTRIBUTE_MODE', 'DATE').upper()

    from_adjacent_id = "from_adjacent_id"
    to_adjacent_id = "to_adjacent_id"
    id_field_name = "FACILITYID"
    xy_tolerance = float(os.getenv('XY_TOLERANCE', 0.001))

    if attribute_mode == 'MATERIAL':
        # Material mode configuration
        source_field = "PIPE_TYPE"
        from_value_field = "From_Material"
        to_value_field = "To_Material"
        field_type = "SHORT"
        #field_length = 50
        
        #value_map = {
        #    1: "PVC",
        #    2: "RCP",
        #    3: "Cast Iron",
        #    4: "Ductile Iron",
        #    5: "VCP",
        #    6: "R.C.C.P",
        #    None: "Unknown",
        #    0: "Unknown",
        #    "N/A": "Unknown"
        #}

        #add_required_fields(projected_fc, from_value_field, to_value_field, field_type)
        #calc_results = calculate_adjacent_attributes(projected_fc, id_field_name, source_field, xy_tolerance)

    elif attribute_mode == 'OWNER':
        # Material mode configuration
        source_field = "OWNER"
        from_value_field = "From_Owner"
        to_value_field = "To_Owner"
        field_type = "SHORT"
    
    elif attribute_mode == 'DATE':
        # Date mode configuration
        source_field = "ASB_DATE"
        from_value_field = "From_ASB_DATE"
        to_value_field = "To_ASB_DATE"
        field_type = "DATE"
        #value_map = None  # No mapping needed for dates

        #add_required_fields(projected_fc, from_value_field, to_value_field, field_type)
        #calc_results = calculate_adjacent_attributes(projected_fc, id_field_name, source_field, xy_tolerance)

    else:
        print(f"Unknown ATTRIBUTE_MODE: {attribute_mode}. Use 'MATERIAL' or 'DATE'.")
        return
    
    add_required_fields(projected_fc, from_value_field, to_value_field, field_type)
    calc_results = calculate_adjacent_attributes(projected_fc, id_field_name, source_field, xy_tolerance)

    update_fields(projected_fc, calc_results, from_adjacent_id, to_adjacent_id, from_value_field, to_value_field)

    print(f"\nScript finished for {attribute_mode} mode.")


if __name__ == "__main__":
    run()