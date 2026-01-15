import os
import math
import arcpy
from shared import set_environment


def get_projected_feature_class(in_fc, out_fc, out_coordinate_system, geographic_transformation):
    """
    Project a feature class using the geographic coordinate system WGS84 to a specified coordinate system using the given transformation.
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
    """
    print("Checking and adding required fields on the projected feature class...")
    existing_fields = [f.name for f in arcpy.ListFields(feature_class)]
    adj_field_length = 50

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


def normalize_angle(angle):
    """Normalize angle to 0-360 range"""
    return angle % 360


def angle_difference(angle1, angle2):
    """
    Calculate the smallest angle difference between two bearings.
    Returns a value between 0 and 180.
    """
    diff = abs(angle1 - angle2)
    if diff > 180:
        diff = 360 - diff
    return diff


def calculate_bearing_to_point(from_x, from_y, to_x, to_y):
    """
    Calculate the bearing from one point to another.
    """
    if from_x == to_x and from_y == to_y:
        return None
    delta_x = to_x - from_x
    delta_y = to_y - from_y
    angle_radians = math.atan2(delta_y, delta_x)
    angle_degrees = math.degrees(angle_radians)
    bearing = (90 - angle_degrees + 360) % 360
    return bearing


def is_segment_ahead_in_flow(current_bearing, from_x, from_y, connected_start_x, connected_start_y, connected_end_x, connected_end_y):
    """
    Determine if a connected segment is positioned ahead in the direction of flow.
    Returns True if the segment's connection point is in the forward direction (within 90 degrees).
    """
    if current_bearing is None:
        return False
    
    bearing_to_start = calculate_bearing_to_point(from_x, from_y, connected_start_x, connected_start_y)
    bearing_to_end = calculate_bearing_to_point(from_x, from_y, connected_end_x, connected_end_y)
    
    if bearing_to_start is None and bearing_to_end is None:
        return False
    
    if bearing_to_start is not None:
        angle_diff_start = angle_difference(current_bearing, bearing_to_start)
    else:
        angle_diff_start = 180
        
    if bearing_to_end is not None:
        angle_diff_end = angle_difference(current_bearing, bearing_to_end)
    else:
        angle_diff_end = 180
    
    # The segment is "ahead" if at least one of its points is within 90 degrees of our flow direction
    min_angle = min(angle_diff_start, angle_diff_end)
    return min_angle < 90


def calculate_flow_compatibility(current_bearing, current_start_x, current_start_y, current_end_x, current_end_y,
                                 connection_point, connected_bearing, connected_start_x, connected_start_y, 
                                 connected_end_x, connected_end_y):
    """
    Calculate compatibility score for flow direction and position.
    Lower scores are better.
    
    Scoring:
    - Segments ahead/behind in flow direction: 0-180 (based on alignment)
    - Segments perpendicular/parallel: 500+ (heavily penalized)
    - Weight: 80% position, 20% flow direction match
    """
    if current_bearing is None or connected_bearing is None:
        return 999
    
    current_bearing = normalize_angle(current_bearing)
    connected_bearing = normalize_angle(connected_bearing)
    
    if connection_point == 'end':
        # Flow going OUT from current segment's end point
        is_ahead = is_segment_ahead_in_flow(
            current_bearing, current_end_x, current_end_y,
            connected_start_x, connected_start_y, connected_end_x, connected_end_y
        )
        
        if not is_ahead:
            # Segment is perpendicular or behind - heavily penalize
            position_score = 500
        else:
            # Segment is ahead - calculate alignment
            bearing_to_start = calculate_bearing_to_point(current_end_x, current_end_y, 
                                                          connected_start_x, connected_start_y)
            bearing_to_end = calculate_bearing_to_point(current_end_x, current_end_y,
                                                        connected_end_x, connected_end_y)
            
            if bearing_to_start is not None:
                angle_to_start = angle_difference(current_bearing, bearing_to_start)
            else:
                angle_to_start = 180
                
            if bearing_to_end is not None:
                angle_to_end = angle_difference(current_bearing, bearing_to_end)
            else:
                angle_to_end = 180
            
            position_score = min(angle_to_start, angle_to_end)
        
        # Flow direction alignment
        flow_score = angle_difference(current_bearing, connected_bearing)
        
        # 80% position, 20% flow direction
        compatibility = (position_score * 0.8) + (flow_score * 0.2)
        
    else:  # connection_point == 'start'
        # Flow coming INTO current segment's start point
        opposite_bearing = normalize_angle(current_bearing + 180)
        is_behind = is_segment_ahead_in_flow(
            opposite_bearing, current_start_x, current_start_y,
            connected_start_x, connected_start_y, connected_end_x, connected_end_y
        )
        
        if not is_behind:
            position_score = 500
        else:
            bearing_to_start = calculate_bearing_to_point(current_start_x, current_start_y,
                                                          connected_start_x, connected_start_y)
            bearing_to_end = calculate_bearing_to_point(current_start_x, current_start_y,
                                                        connected_end_x, connected_end_y)
            
            expected_direction = opposite_bearing
            
            if bearing_to_start is not None:
                angle_to_start = angle_difference(expected_direction, bearing_to_start)
            else:
                angle_to_start = 180
                
            if bearing_to_end is not None:
                angle_to_end = angle_difference(expected_direction, bearing_to_end)
            else:
                angle_to_end = 180
            
            position_score = min(angle_to_start, angle_to_end)
        
        expected_flow = normalize_angle(current_bearing + 180)
        flow_score = angle_difference(expected_flow, connected_bearing)
        
        # 80% position, 20% flow direction
        compatibility = (position_score * 0.8) + (flow_score * 0.2)
    
    return compatibility


def get_adjacent_ids(feature_data, xy_tolerance):
    """
    Get the adjacent IDs for each feature, sorted by flow compatibility.
    Uses position-aware scoring: segments ahead in flow get priority over perpendicular/parallel segments.
    """
    print("Building spatial index for endpoints...")
    
    start_points = {}
    end_points = {}
    
    def round_coords(x, y, tolerance):
        factor = 1.0 / tolerance
        return (round(x * factor), round(y * factor))
    
    for oid, feat_id, sx, sy, ex, ey, bearing, _ in feature_data:
        start_key = round_coords(sx, sy, xy_tolerance)
        end_key = round_coords(ex, ey, xy_tolerance)
        
        if start_key not in start_points:
            start_points[start_key] = []
        start_points[start_key].append((oid, feat_id, sx, sy, ex, ey, bearing))
        
        if end_key not in end_points:
            end_points[end_key] = []
        end_points[end_key].append((oid, feat_id, sx, sy, ex, ey, bearing))
    
    from_adjacent_ids = {}
    to_adjacent_ids = {}
    
    for oid, _, _, _, _, _, _, _ in feature_data:
        from_adjacent_ids[oid] = []
        to_adjacent_ids[oid] = []
    
    print("Finding adjacent segments with position and flow analysis...")
    processed_count = 0
    
    for oid, feat_id, sx, sy, ex, ey, bearing, _ in feature_data:
        start_key = round_coords(sx, sy, xy_tolerance)
        end_key = round_coords(ex, ey, xy_tolerance)
        
        # FROM (start point connections)
        connected_at_start = []
        
        if start_key in start_points:
            for other_oid, other_id, other_sx, other_sy, other_ex, other_ey, other_bearing in start_points[start_key]:
                if other_oid != oid:
                    dist = math.sqrt((sx - other_sx)**2 + (sy - other_sy)**2)
                    if dist < xy_tolerance:
                        score = calculate_flow_compatibility(
                            bearing, sx, sy, ex, ey, 'start', other_bearing,
                            other_sx, other_sy, other_ex, other_ey
                        )
                        connected_at_start.append((other_id, score))
        
        if start_key in end_points:
            for other_oid, other_id, other_sx, other_sy, other_ex, other_ey, other_bearing in end_points[start_key]:
                if other_oid != oid:
                    dist = math.sqrt((sx - other_ex)**2 + (sy - other_ey)**2)
                    if dist < xy_tolerance:
                        score = calculate_flow_compatibility(
                            bearing, sx, sy, ex, ey, 'start', other_bearing,
                            other_sx, other_sy, other_ex, other_ey
                        )
                        connected_at_start.append((other_id, score))
        
        seen_ids = set()
        sorted_from = []
        for seg_id, score in sorted(connected_at_start, key=lambda x: x[1]):
            if seg_id not in seen_ids:
                sorted_from.append(seg_id)
                seen_ids.add(seg_id)
        from_adjacent_ids[oid] = sorted_from
        
        # TO (end point connections)
        connected_at_end = []
        
        if end_key in start_points:
            for other_oid, other_id, other_sx, other_sy, other_ex, other_ey, other_bearing in start_points[end_key]:
                if other_oid != oid:
                    dist = math.sqrt((ex - other_sx)**2 + (ey - other_sy)**2)
                    if dist < xy_tolerance:
                        score = calculate_flow_compatibility(
                            bearing, sx, sy, ex, ey, 'end', other_bearing,
                            other_sx, other_sy, other_ex, other_ey
                        )
                        connected_at_end.append((other_id, score))
        
        if end_key in end_points:
            for other_oid, other_id, other_sx, other_sy, other_ex, other_ey, other_bearing in end_points[end_key]:
                if other_oid != oid:
                    dist = math.sqrt((ex - other_ex)**2 + (ey - other_ey)**2)
                    if dist < xy_tolerance:
                        score = calculate_flow_compatibility(
                            bearing, sx, sy, ex, ey, 'end', other_bearing,
                            other_sx, other_sy, other_ex, other_ey
                        )
                        connected_at_end.append((other_id, score))
        
        seen_ids = set()
        sorted_to = []
        for seg_id, score in sorted(connected_at_end, key=lambda x: x[1]):
            if seg_id not in seen_ids:
                sorted_to.append(seg_id)
                seen_ids.add(seg_id)
        to_adjacent_ids[oid] = sorted_to
        
        processed_count += 1
        if processed_count % 1000 == 0:
            print(f"Processed {processed_count} features for adjacency...")
    
    print("Finished finding adjacent segments.")
    return from_adjacent_ids, to_adjacent_ids


def update_fields(feature_class, feature_data, direction_float_field, direction_text_field, xy_tolerance):
    """
    Update the fields in the feature class with the calculated values.
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
                    from_ids = from_adjacent_ids.get(oid, [])
                    to_ids = to_adjacent_ids.get(oid, [])
                    
                    row[1] = from_ids[0] if len(from_ids) > 0 else None
                    row[2] = from_ids[1] if len(from_ids) > 1 else None
                    row[3] = from_ids[2] if len(from_ids) > 2 else None
                    row[4] = from_ids[3] if len(from_ids) > 3 else None
                    row[5] = to_ids[0] if len(to_ids) > 0 else None
                    row[6] = to_ids[1] if len(to_ids) > 1 else None
                    row[7] = to_ids[2] if len(to_ids) > 2 else None
                    row[8] = to_ids[3] if len(to_ids) > 3 else None
                    row[9] = bearing
                    row[10] = direction_text
                    
                    if len(from_ids) > 4:
                        print(f"WARNING: Feature {feat_id} (OID {oid}) has {len(from_ids)} connections at START point (exceeds 4)")
                    if len(to_ids) > 4:
                        print(f"WARNING: Feature {feat_id} (OID {oid}) has {len(to_ids)} connections at END point (exceeds 4)")
                else:
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