from arcgis.gis import GIS
from arcgis.features import FeatureLayer, Feature, use_proximity
from arcgis.geometry import Point, SpatialReference
from arcgis.geometry.filters import intersects, within
import math
from time import sleep
import copy
from base_logger import logger

'''
Fix topology errors in a utility line layer (in a feature service hosted in ArcGIS Online) by snapping endpoints of line segments to the nearest point within a specified tolerance.
for now:
- do not try to snap line endpoints to each other
- do not try to move point features
'''

# --- CONFIG ---
GIS_LOGIN = "home"
POINT_URL = "https://services2.arcgis.com/kXGqZY4GIOcEYxoF/arcgis/rest/services/Sanitary_Sewer_Copy_2/FeatureServer/5"
LINE_URL = "https://services2.arcgis.com/kXGqZY4GIOcEYxoF/arcgis/rest/services/Sanitary_Sewer_Copy_2/FeatureServer/4"
# lines below have been modified by this script
#LINE_URL = "https://services2.arcgis.com/kXGqZY4GIOcEYxoF/arcgis/rest/services/Sanitary_Sewer_Subset_D1/FeatureServer/1"
#POINT_URL = "https://services2.arcgis.com/kXGqZY4GIOcEYxoF/arcgis/rest/services/Sanitary_Sewer_Subset_D1/FeatureServer/0"
#LINE_URL = "https://services2.arcgis.com/kXGqZY4GIOcEYxoF/arcgis/rest/services/Sanitary_Sewer_Subset_D/FeatureServer/1"
#POINT_URL = "https://services2.arcgis.com/kXGqZY4GIOcEYxoF/arcgis/rest/services/Sanitary_Sewer_Subset_D/FeatureServer/0"
#LINE_URL = "https://services2.arcgis.com/kXGqZY4GIOcEYxoF/arcgis/rest/services/Sanitary_Sewer_Copy/FeatureServer/12"
#POINT_URL = "https://services2.arcgis.com/kXGqZY4GIOcEYxoF/arcgis/rest/services/Sanitary_Sewer_Copy/FeatureServer/11"
#POINT_URL = "https://services2.arcgis.com/kXGqZY4GIOcEYxoF/arcgis/rest/services/Sanitary_Sewer_Subset_D2/FeatureServer/1"
#LINE_URL = "https://services2.arcgis.com/kXGqZY4GIOcEYxoF/arcgis/rest/services/Sanitary_Sewer_Subset_D2/FeatureServer/0"


# TODO - remove constants if not necessary or get_snap_tolerance_degrees()
BUFFER_WIDTH_FEET = 1
# APPROX_FEET_IN_DEGREE used only for logging - original value: 306604.32
#APPROX_FEET_IN_DEGREE = 302114.8036
APPROX_FEET_IN_DEGREE = 306604.32
SR_WGS84 = SpatialReference(4326)
SR_PROJECTED = SpatialReference(2276)
CONVERSION_FACTOR_FEET_TO_DEGREES = 3.31e-6

def get_snap_tolerance_degrees(snap_tolerance_feet: float) -> float:
    """
    Convert snap tolerance from feet to degrees for City of Lewisville.
    """
    snap_tolerance_degrees = snap_tolerance_feet * CONVERSION_FACTOR_FEET_TO_DEGREES
    logger.info(f"Snap tolerance: {snap_tolerance_feet} feet in degrees: {snap_tolerance_degrees}")   
    return snap_tolerance_degrees


def get_buffer_feature_layer(gis, item_id=None, point_layer=None, buffer_distance=None):
    """
    Return a FeatureLayer of buffered features from the specified item in ArcGIS Online or a new buffer created from the given point layer.
    Requires either item_id OR point_layer and buffer_distance to be specified
    :param gis: GIS object - the GIS connection to use
    :param item_id: str or None - item id of the existing item to fetch, if None, item will be created using other arguments
    :param point_layer: FeatureLayer or None - if provided, will use this layer to create buffers
    :param buffer_distance: float or None - distance in feet to create buffers, can be None if using an existing item
    :return: FeatureLayer or None if item not found
    """
    if not item_id and (not point_layer or not buffer_distance):
        logger.error("Either item_id or (point_layer and buffer_distance) must be specified.")
        return None
    if item_id:
        item = gis.content.get(item_id)
        if item:
            buffer_feature_layer = item.layers[0]
    else:
        # create_buffers() returns a FeatureLayer (in version 2.4 of API) - 9/2/25 using Pro 3.5.2 (2.5 of API), returning a FeatureCollection
        buffer_feature_layer = use_proximity.create_buffers(point_layer, distances=[buffer_distance], units="Feet", output_name=item_id)
    try:
        buffer_feature_set = buffer_feature_layer.query(where="1=1", return_geometry=False)
    except Exception as e:
        logger.error(f"Error querying buffer feature layer: {e}")
    # for use with Pro 3.5.2 (2.5 of API)
    #buffer_feature_set = buffer_feature_layer.properties.featureSet
    logger.info(f"Buffer feature layer contains {len(buffer_feature_set.features)} features.")
    logger.debug(f"type of buffer_feature_layer: {type(buffer_feature_layer)}")
    return buffer_feature_layer

# --- GEOMETRY HELPERS ---

def get_endpoints(line_geom: dict) -> list:
    """
    Extracts start and end Points from a line geometry.
    :param line_geom: dict - the geometry of the line feature
    :return: list of Point objects - start and end points of the line
    """
    if line_geom and line_geom['paths']:
        path = line_geom['paths'][0]
        sr = line_geom['spatialReference']
        endpoints = [
            Point({"x": path[0][0], "y": path[0][1], "spatialReference": sr}),
            Point({"x": path[-1][0], "y": path[-1][1], "spatialReference": sr})
        ]
        logger.debug(f'original endpoints: {endpoints}')
        return endpoints
    else:
        logger.warning(f"**********Line geometry has no paths. line_geom: {line_geom}**********")
        return []


def get_point_distance(p1: Point, p2: Point) -> float:
    """
    Return the Euclidean distance between two Points.
    :param p1: Point - first point
    :param p2: Point - second point
    :return: float - the distance between the two points
    """
    return math.hypot(p1.x - p2.x, p1.y - p2.y)


def get_nearest_point(point: Point, point_list: list) -> Point:
    """
    Find the nearest point in the point layer to the given point that is also within the specified width of the buffer.
    :param point: Point - the line endpoint to find the nearest neighbor for
    :param point_list: list of Point objects - the list containing candidate points (utility point features)
    :return: Point - the nearest point found, or None if no points are in the layer
    """
    nearest_point = None
    min_distance = float("inf")
    logger.debug(f'point IN QUESTION: {(point)}')
    for candidate in point_list:
        logger.debug(f'candidate: {(candidate)}')
        distance = get_point_distance(point, candidate)
        if distance < min_distance:
            min_distance = distance
            nearest_point = candidate
    if min_distance > BUFFER_WIDTH_FEET * CONVERSION_FACTOR_FEET_TO_DEGREES:
        nearest_point = None
    logger.debug(f'returning nearest_point: {nearest_point} with distance {min_distance * APPROX_FEET_IN_DEGREE} feet')
    return nearest_point


def is_snapped(endpoint: Point, target_point: Point, tolerance: float) -> bool:
    """
    Check whether an endpoint is already snapped to the point.
    :param endpoint: Point - the endpoint to check
    :param target_point: Point - the target point to check against
    :param tolerance: float - the snapping tolerance in degrees
    :return: bool - True if the endpoint is within the tolerance of the point, False otherwise
    """
    distance = get_point_distance(endpoint, target_point)
    snapped = distance <= tolerance
    #logger.info(f"Endpoint {endpoint} is {'snapped' if snapped else 'not snapped'} to target point {target_point} with gap distance {distance} feet.")
    logger.info(f"Endpoint is {'snapped' if snapped else 'not snapped'} to target point with gap distance of {distance} degrees, or approximately {round(distance * APPROX_FEET_IN_DEGREE, 3)} feet.")
    return snapped


def snap_endpoint_to_point(line_feature, endpoint_index, new_point: Point):
    """
    Modify the endpoint (start or end) of a line geometry.
    :param line_feature: Feature object - the line feature to modify
    :param endpoint_index: int - 0 for start, 1 for end
    :param new_point: Point - the new location for the endpoint
    :return: Feature object - the modified line feature with updated endpoint
    """
    original_geom = line_feature.geometry
    # use deep copy to prevent reuse of geometry object references
    path = copy.deepcopy(original_geom['paths'][0])
    # are some line segments made up of more than 2 points???
    logger.debug(f"Original path before snapping: {path}")
    # no functional change between four lines below and last version, just cleaner
    # TODO - adjust rounding if necessary - may need to explicitly round coordinates here to ensure updates are detected by AGO
    if endpoint_index == 0:
        path[0] = [round(new_point.x, 8), round(new_point.y, 8)]
    else:
        path[-1] = [round(new_point.x, 8), round(new_point.y, 8)]
    line_feature.geometry = {"paths": [path], "spatialReference": line_feature.geometry['spatialReference']}
    return line_feature


def get_intersecting_buffer_features(line_feature, buffer_layer):
    """
    Get buffer feature(s) that intersect with the given line feature (should return between 0 and 2 buffer features if buffer around each point is < 1 foot).
    :param line_feature: Feature object - the line feature to check against
    :param buffer_layer: FeatureLayer - the layer containing buffer features
    :return: list of intersecting buffer features
    """
    line_geom = line_feature.geometry
    query_filter = intersects(line_geom)
    intersecting_buffers = buffer_layer.query(geometry_filter=query_filter,
                                        return_geometry=True,
                                        out_fields="*").features
    logger.info(f"Found {len(intersecting_buffers)} buffer feature(s) intersecting line {line_feature.attributes.get('FACILITYID')}.")
    return intersecting_buffers


def get_points_in_buffer(point_layer, buffer_feature):
    """
    Return the point(s) from the given point layer that fall within the given buffer feature.
    :param point_layer: FeatureLayer object - the point layer containing points that may be within the given buffer
    :param buffer_feature: Feature object - the buffer feature to check against
    :return: list of points within the buffer
    """
    logger.debug("Entered get_points_in_buffer()")
    buffer_geom = buffer_feature.geometry
    query_filter = intersects(buffer_geom)
    logger.debug("Attempting to get point(s) within buffer.")
    features = point_layer.query(geometry_filter=query_filter,
                              return_geometry=True, out_fields = []).features
                              #out_fields="*").features
    # convert features to Points
    points = [Point({"x": f.geometry['x'], "y": f.geometry['y'], "spatialReference": f.geometry['spatialReference']}) for f in features]
    logger.debug(f"Points within buffer: {points}")
    return points


def process_endpoint(line_feature: Feature, endpoint: Point, endpoint_index: int, 
                     buffer_features: list, point_layer: FeatureLayer, snap_tolerance_degrees: float):
    """
    For a single endpoint:
    - Check if endpoint is within any of the given buffer features
    - If so, get points within that buffer and snap to nearest point if not already snapped
    :param line_feature: Feature object - the line feature being processed
    :param endpoint: Point object - the endpoint to process
    :param endpoint_index: int - 0 for start, 1 for end
    :param buffer_features: list of Feature objects - the buffer features to check against
    :param point_layer: FeatureLayer object - the layer containing point features
    :param snap_tolerance_degrees: float - the snapping tolerance in degrees
    :return: tuple (bool, Feature object (line)) - boolean indicating if endpoint of line was updated, and the line feature which may or may not be updated
    """
    updated = False
    ep_in_question = None
    target_points = []
    for buffer_feature in buffer_features:
        if within(endpoint, buffer_feature.geometry):
            ep_in_question = endpoint
            target_points = target_points + get_points_in_buffer(point_layer, buffer_feature)
    #final_target_points = []
    if ep_in_question and target_points:
        # Snap the endpoint to the nearest target point
        nearest_point = get_nearest_point(ep_in_question, target_points)
        if nearest_point and not is_snapped(ep_in_question, nearest_point, snap_tolerance_degrees):
            logger.info(f"Endpoint {ep_in_question} will be snapped to nearest point {nearest_point}.")
            updated_line_feature = snap_endpoint_to_point(line_feature, endpoint_index, nearest_point)
            logger.info(f"Snapped endpoint {endpoint_index} of line {line_feature.attributes.get('FACILITYID')} to point {nearest_point}.")
            logger.debug(f"Updated line feature geometry: {updated_line_feature.geometry}")
            updated = True
            return (updated, updated_line_feature)
        else:
            logger.info(f"Endpoint {ep_in_question} is already snapped to nearest point {nearest_point}.")
    return (updated, line_feature)


def process_line(line_feature, buffer_layer, point_layer, snap_tolerance_feet: float):
    """
    For a single line:
    - Get endpoints
    - For each endpoint, if endpoint is not snapped to a point within ______ (that point's buffer), snap it to that point
    :param line_feature: Feature object - the line feature to process
    :param buffer_layer: FeatureLayer object - the layer containing buffer features
    :param point_layer: FeatureLayer object - the layer containing point features
    :return: tuple (bool, Feature object (line)) - boolean indicating if line was updated, and the line feature which may or may not be updated
    """
    endpoints = get_endpoints(line_feature.geometry)
    if not endpoints:
        logger.warning("**********Line geometry has no endpoints.**********")
        return (False, line_feature)
    #raise ValueError("Temp dummy error for testing error handling.")
    buffer_features = get_intersecting_buffer_features(line_feature, buffer_layer)
    ep1, ep2 = endpoints[0], endpoints[1]
    snap_tolerance_degrees = get_snap_tolerance_degrees(snap_tolerance_feet)
    ep1_updated, processed_line_feature = process_endpoint(line_feature, ep1, 0, buffer_features, point_layer, snap_tolerance_degrees)
    if ep1_updated:
        ep2_updated, final_line_feature = process_endpoint(processed_line_feature, ep2, 1, buffer_features, point_layer, snap_tolerance_degrees)
    else:
        ep2_updated, final_line_feature = process_endpoint(line_feature, ep2, 1, buffer_features, point_layer, snap_tolerance_degrees)

    if ep1_updated or ep2_updated:
        logger.info(f"Updated at least one endpoint of line {final_line_feature.attributes.get('FACILITYID')} with new geometry.")
        return True, final_line_feature
    else:
        logger.info(f"No updates made to line {line_feature.attributes.get('FACILITYID')}.")
        return False, line_feature
    

def batch_edit_features(layer, features, batch_size=500):
    """
    Safely edits features in batches to avoid request limits.
    :param layer: FeatureLayer object
    :param features: list of Feature objects to update
    :param batch_size: int - max number of features per request
    """

    total = len(features)
    for i in range(0, total, batch_size):
        batch = features[i:i + batch_size]
        try:
            result = layer.edit_features(updates=batch)
            logger.info(f"Batch {i//batch_size + 1}: Processed {len(batch)} features. Result: {result}")
            sleep(0.5)  # optional throttle to avoid rate limiting
        except Exception as e:
            logger.error(f"Batch {i//batch_size + 1} failed: {e}")



def main(snap_tolerance_feet=0.01):
    gis = GIS(GIS_LOGIN)
    line_layer = FeatureLayer(LINE_URL)
    point_layer = FeatureLayer(POINT_URL)

    # id for 'Simplified Sewer Point Buffer 1 Foot as of 20250902 1216pm'
    buffer_item_id = '558bbf511c1749669dec0ded02501da1'
    buffer_feature_layer = get_buffer_feature_layer(gis, item_id=buffer_item_id)
    #buffer_feature_layer = get_buffer_feature_layer(gis, item_id=None, point_layer=point_layer, buffer_distance=BUFFER_WIDTH_FEET)
    line_feature_set = line_layer.query(return_geometry=True)
    updated_line_facility_ids = []
    skipped_line_facility_ids = []
    # Only collect features actually updated
    updated_features = []
    updated_count = 0  

    for line_feature in line_feature_set.features:
        line_fid = line_feature.attributes.get('FACILITYID')
        logger.info(f"\nProcessing line feature: {line_fid}")
        
        try:
            line_updated, processed_line = process_line(line_feature, buffer_feature_layer, 
                                                        point_layer, snap_tolerance_feet)
            if line_updated:
                updated_count += 1
                updated_features.append(processed_line)  # Only append if updated
                updated_line_facility_ids.append(line_fid)
        except Exception as e:
            skipped_line_facility_ids.append(line_fid)
            logger.warning(f"Error processing line feature {line_fid}: {e}")

    logger.info(f"Total updated lines to apply: {updated_count}")
    logger.info(f"Facility IDs of lines to be updated: {updated_line_facility_ids}")

    if updated_features:
        batch_edit_features(line_layer, updated_features)

    
if __name__ == "__main__":
    main()
