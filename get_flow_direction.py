import os
import math
import arcpy
from shared import set_environment


def get_projected_feature_class(in_fc, out_fc, out_coordinate_system, geographic_transformation):
    """
    Project a feature class using the geographic coordinate system WGS84 to a specified coordinate system using the given transformation.
    :param in_fc - string: Path to the input feature class.
    :param out_fc - string: Path to the output feature class.
    :param out_coordinate_system - string: The output coordinate system (e.g., WKID or path).
    :param geographic_transformation - string: The geographic transformation to use.
    return: output feature class path
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


def add_required_fields(feature_class, direction_float_field, direction_text_field):
    """
    Add required fields to the feature class if they don't already exist.
    :param feature_class: The projected feature class to check and add fields to.
    :param direction_float_field: The name of the field for the direction in degrees.
    :param direction_text_field: The name of the field for the direction as text.
    """
    print("Checking and adding required fields on the projected feature class...")

    existing_fields = [f.name for f in arcpy.ListFields(feature_class)]

    adj_field_length = 50

    # Create fields for direction and multiple adjacent IDs (4 each)
    fields_to_add = {
        "from_adjacent_id_1": "TEXT",
        "from_adjacent_id_2": "TEXT",
        "from_adjacent_id_3": "TEXT",
        "from_adjacent_id_4": "TEXT",
        "to_adjacent_id_1": "TEXT",
        "to_adjacent_id_2": "TEXT",
        "to_adjacent_id_3": "TEXT",
        "to_adjacent_id_4": "TEXT",
        direction_float_field: "DOUBLE",
        direction_text_field: "TEXT"
    }

    for field_name, field_type in fields_to_add.items():
        if field_name not in existing_fields:
            print(f"Adding field: {field_name} ({field_type})")
            if field_type == "TEXT":
                arcpy.AddField_management(feature_class, field_name, field_type, field_length=adj_field_length)
            else:
                arcpy.AddField_management(feature_class, field_name, field_type)
        else:
            print(f"Field '{field_name}' already exists.")


def calculate_bearing(x1, y1, x2, y2):
    """
    Calculate the bearing from point (x1, y1) to point (x2, y2) in degrees, clockwise from North (0-360).
    :param x1 - float: X coordinate of the start point.
    :param y1 - float: Y coordinate of the start point.
    :param x2 - float: X coordinate of the end point.
    :param y2 - float: Y coordinate of the end point.
    :return: Bearing in degrees (0-360) or None if the points are the same.
    """
    if x1 == x2 and y1 == y2:
        return None

    delta_x = x2 - x1
    delta_y = y2 - y1
    angle_radians = math.atan2(delta_y, delta_x)
    angle_degrees = math.degrees(angle_radians)
    bearing = (90 - angle_degrees + 360) % 360

    return bearing


def get_direction_text(bearing):
    """
    Convert a bearing (in degrees) to a cardinal/intercardinal direction text.
    :param bearing: Bearing in degrees (0-360).
    :return: Direction text (N, NE, E, SE, S, SW, W, NW) or None if bearing is None.
    """
    if bearing is None:
        return None
    
    bearing = bearing % 360

    if (bearing >= 337.5 and bearing <= 360) or (bearing >= 0 and bearing < 22.5):
        return "N"
    elif (bearing >= 22.5 and bearing < 67.5):
        return "NE"
    elif (bearing >= 67.5 and bearing < 112.5):
        return "E"
    elif (bearing >= 112.5 and bearing < 157.5):
        return "SE"
    elif (bearing >= 157.5 and bearing < 202.5):
        return "S"
    elif (bearing >= 202.5 and bearing < 247.5):
        return "SW"
    elif (bearing >= 247.5 and bearing < 292.5):
        return "W"
    elif (bearing >= 292.5 and bearing < 337.5):
        return "NW"
    else:
        return None


def calculate_direction_values(feature_class, id_field):
    """
    Read the feature geometries from the feature class and calculate direction values.
    :param feature_class - string: Path of the projected feature class to read from.
    :param id_field - string: The name of the unique ID field in the feature class.
    :return feature_data: List of tuples containing feature data with calculated direction values.
    """
    print("Reading projected feature geometries and calculating direction...")
    feature_data = []
    fields_for_processing = ['OID@', id_field, 'SHAPE@']

    with arcpy.da.SearchCursor(feature_class, fields_for_processing) as cursor:
        for row in cursor:
            oid = row[0]
            feat_id = row[1]
            shape = row[2]

            if shape is None:
                continue

            try:
                start_point = shape.firstPoint
                end_point = shape.lastPoint
                sx, sy = start_point.X, start_point.Y
                ex, ey = end_point.X, end_point.Y

                bearing = calculate_bearing(sx, sy, ex, ey)
                direction_text = get_direction_text(bearing)

            except Exception as e:
                bearing = None
                direction_text = None
                continue

            feature_data.append((oid, feat_id, sx, sy, ex, ey, bearing, direction_text))

    print(f"Read data and calculated direction for {len(feature_data)} features.")
    return feature_data


def get_adjacent_ids(feature_data, xy_tolerance):
    """
    Get the adjacent IDs for each feature in the feature class, supporting multiple connections per endpoint.
    :param feature_data: List of tuples containing feature data with calculated direction values.
    :param xy_tolerance: Tolerance for comparing point locations in the projected coordinate system units.
    :return: Two dictionaries holding lists of from_adjacent_ids and to_adjacent_ids for each OID
    """
    print("Building spatial index for endpoints...")
    
    # Build dictionaries to group features by their start and end points
    # Key: rounded coordinates (to handle tolerance), Value: list of (oid, feat_id, is_start_point)
    start_points = {}
    end_points = {}
    
    def round_coords(x, y, tolerance):
        """Round coordinates to a grid based on tolerance for grouping"""
        factor = 1.0 / tolerance
        return (round(x * factor), round(y * factor))
    
    # Build spatial index
    for oid, feat_id, sx, sy, ex, ey, _, _ in feature_data:
        start_key = round_coords(sx, sy, xy_tolerance)
        end_key = round_coords(ex, ey, xy_tolerance)
        
        if start_key not in start_points:
            start_points[start_key] = []
        start_points[start_key].append((oid, feat_id, sx, sy))
        
        if end_key not in end_points:
            end_points[end_key] = []
        end_points[end_key].append((oid, feat_id, ex, ey))
    
    # Initialize dictionaries to store adjacent IDs (as lists)
    from_adjacent_ids = {}
    to_adjacent_ids = {}
    
    for oid, _, _, _, _, _, _, _ in feature_data:
        from_adjacent_ids[oid] = []
        to_adjacent_ids[oid] = []
    
    print("Finding adjacent segments at endpoints...")
    processed_count = 0
    
    for oid, feat_id, sx, sy, ex, ey, _, _ in feature_data:
        start_key = round_coords(sx, sy, xy_tolerance)
        end_key = round_coords(ex, ey, xy_tolerance)
        
        # Find segments connected at the START point
        # Check both start_points and end_points dictionaries for matches
        connected_at_start = []
        
        # Check if other segments have their start point here
        if start_key in start_points:
            for other_oid, other_id, other_x, other_y in start_points[start_key]:
                if other_oid != oid:  # Don't connect to self
                    dist = math.sqrt((sx - other_x)**2 + (sy - other_y)**2)
                    if dist < xy_tolerance:
                        connected_at_start.append(other_id)
        
        # Check if other segments have their end point here
        if start_key in end_points:
            for other_oid, other_id, other_x, other_y in end_points[start_key]:
                if other_oid != oid:  # Don't connect to self
                    dist = math.sqrt((sx - other_x)**2 + (sy - other_y)**2)
                    if dist < xy_tolerance:
                        connected_at_start.append(other_id)
        
        from_adjacent_ids[oid] = list(set(connected_at_start))  # Remove duplicates
        
        # Find segments connected at the END point
        connected_at_end = []
        
        # Check if other segments have their start point here
        if end_key in start_points:
            for other_oid, other_id, other_x, other_y in start_points[end_key]:
                if other_oid != oid:
                    dist = math.sqrt((ex - other_x)**2 + (ey - other_y)**2)
                    if dist < xy_tolerance:
                        connected_at_end.append(other_id)
        
        # Check if other segments have their end point here
        if end_key in end_points:
            for other_oid, other_id, other_x, other_y in end_points[end_key]:
                if other_oid != oid:
                    dist = math.sqrt((ex - other_x)**2 + (ey - other_y)**2)
                    if dist < xy_tolerance:
                        connected_at_end.append(other_id)
        
        to_adjacent_ids[oid] = list(set(connected_at_end))  # Remove duplicates
        
        processed_count += 1
        if processed_count % 1000 == 0:
            print(f"Processed {processed_count} features for adjacency...")
    
    print("Finished finding adjacent segments.")
    return from_adjacent_ids, to_adjacent_ids


def update_fields(feature_class, feature_data, direction_float_field, direction_text_field, xy_tolerance):
    """
    Update the fields in the feature class with the calculated values.
    :param feature_class: The feature class to update.
    :param direction_float_field: The name of the field for the direction in degrees.
    :param direction_text_field: The name of the field for the direction as text.
    :param xy_tolerance: Tolerance for comparing point locations in the projected coordinate system units.
    """
    print("Updating fields in the feature class...")
    
    update_field_names = [
        'OID@', 
        'from_adjacent_id_1', 'from_adjacent_id_2', 'from_adjacent_id_3', 'from_adjacent_id_4',
        'to_adjacent_id_1', 'to_adjacent_id_2', 'to_adjacent_id_3', 'to_adjacent_id_4',
        direction_float_field, direction_text_field
    ]

    desc = arcpy.Describe(feature_class)
    edit = arcpy.da.Editor(desc.path)

    feature_data_dict = {item[0]: item for item in feature_data}
    from_adjacent_ids, to_adjacent_ids = get_adjacent_ids(feature_data, xy_tolerance)

    try:
        if not edit.isEditing:
            edit.startEditing(False, False)
        edit.startOperation()

        with arcpy.da.UpdateCursor(feature_class, update_field_names) as cursor:
            for row in cursor:
                oid = row[0]
                calculated_data = feature_data_dict.get(oid)

                if calculated_data:
                    _, feat_id, _, _, _, _, bearing, direction_text = calculated_data
                    
                    # Get lists of adjacent IDs (already sorted by flow compatibility)
                    from_ids = from_adjacent_ids.get(oid, [])
                    to_ids = to_adjacent_ids.get(oid, [])
                    
                    # Assign up to 4 from_adjacent_ids
                    row[1] = from_ids[0] if len(from_ids) > 0 else None
                    row[2] = from_ids[1] if len(from_ids) > 1 else None
                    row[3] = from_ids[2] if len(from_ids) > 2 else None
                    row[4] = from_ids[3] if len(from_ids) > 3 else None
                    
                    # Assign up to 4 to_adjacent_ids
                    row[5] = to_ids[0] if len(to_ids) > 0 else None
                    row[6] = to_ids[1] if len(to_ids) > 1 else None
                    row[7] = to_ids[2] if len(to_ids) > 2 else None
                    row[8] = to_ids[3] if len(to_ids) > 3 else None
                    
                    # Assign direction values
                    row[9] = bearing
                    row[10] = direction_text
                    
                    # Warning for more than 4 connections
                    if len(from_ids) > 4:
                        print(f"WARNING: Feature {feat_id} (OID {oid}) has {len(from_ids)} connections at START point (exceeds 4)")
                    if len(to_ids) > 4:
                        print(f"WARNING: Feature {feat_id} (OID {oid}) has {len(to_ids)} connections at END point (exceeds 4)")

                else:
                    # Set all fields to None if feature wasn't processed
                    for i in range(1, len(row)):
                        row[i] = None

                cursor.updateRow(row)

        edit.stopOperation()
        edit.stopEditing(True)
        print("Attribute table updated successfully with adjacent IDs and direction.")

    except Exception as e:
        print(f"Error during attribute table update: {e}")
        if edit.isEditing:
            edit.stopOperation()
            edit.stopEditing(False)


def run():
    set_environment()
    input_fc_name = os.getenv('INPUT_FC')
    input_fc = os.path.join(arcpy.env.workspace, input_fc_name)
    
    spatial_ref_wkid = 2277
    out_coordinate_system = arcpy.SpatialReference(spatial_ref_wkid)
    geographic_transformation = "WGS_1984_(ITRF00)_To_NAD_1983"
    output_fc_name = os.path.join(arcpy.env.workspace, input_fc_name + f'_{str(spatial_ref_wkid)}')
    
    projected_fc = get_projected_feature_class(input_fc, output_fc_name, out_coordinate_system, geographic_transformation)
    
    direction_float = "direction_float"
    direction_text = "direction_text"
    add_required_fields(projected_fc, direction_float, direction_text)
    
    id_field = "FACILITYID"
    feature_data = calculate_direction_values(projected_fc, id_field)
    
    xy_tolerance = 0.001
    print(f"Using XY Tolerance: {xy_tolerance} (in units of the projected coordinate system)")
    update_fields(projected_fc, feature_data, direction_float, direction_text, xy_tolerance)

    print("\nScript finished.")


if __name__ == "__main__":
    run()