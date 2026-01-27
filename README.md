# Clean Utility Data

A series of scripts to:
1. snap line endpoints to nearby point features within a specified distance/tolerance
2. add flow direction to the attribute table of a copy of a line feature layer
3. add new fields to the attribute tables of copies of line or point feature layers containing information on numbers of connected features and specified attributes of features adjacent to a given feature

TODO - add details on numbers 1 and 3 above including material (PIPE_TYPE) updates to this section, Overview, and Usage - see Kyunghee's branch 'modifications-2-materials'

This script adds direction information to the attribute table of a line feature class - direction is determined using the starting and ending point. While this can be done for any line feature class, a model of utility networks brought about the need for it.

## Overview

The script **`get_flow_direction.py`** does the following:

1. creates a copy of the input feature class using the specified projected spatial reference
2. adds attribute table fields to hold the following for each line segment:
    - the id's of adjacent segments
    - the bearing of the line segment
    - a cardinal direction of the line segment - one of 'N', 'S', 'E', 'W', 'NW', 'NE', 'SW', 'SE'
3. populates the new fields

## Input Data

The script operates on geospatial data - a feature class of lines stored in an **ArcGIS geodatabase**. The direction of each line segment in the input feature class is represented by the starting point and ending point used to draw each segment.

## Dependencies

The script requires:
- **ArcGIS Pro version 3.4** with **arcpy**
- **Python 3.x** (as used in ArcGIS)
- **ArcGIS API for Python version 2.4 (for Pro version 3.4)**
- **dotenv**

## Usage

1. Ensure all dependencies are installed and that ArcGIS Pro/ArcMap is available with necessary licenses.
2. Configure the .env file according to the file '.env.example' (.env will not be committed to version control)
3. In the run() function of get_flow_direction.py, modify the values assigned to the following variables: spatial_ref_wkid, geographic_transformation, from_adjacent_id, to_adjacent_id, direction_float, direction_text, id_field, and xy_tolerance - see the docstrings and comments for explanations of these
4. Run get_flow_direction.py

The script can be run as a standalone Python script from a terminal (`python path/to/script.py` or `propy path/to/script.py` if using the 'propy' environment provided with ArcGIS Pro).

### Script Sequence and Outputs

#### Sewer Lines (and probably Water Lines)
1. assign_dates_from_projects.py - assigns as-built dates and 'accept dates' from a list of projects from Laserfiche - if a single project contains multiple date values, the most commonly-occuring value (mode) is assigned; adds field 'As_Built_Date_Source' and updates field with either 'Project As-Built Date' or 'Project Accept Date'

2. get_flow_direction.py - adds four fields to hold id's of adjacent segments on either side of each segment, populates as many of those fields as possible; also adds fields to hold direction/bearing as both a value between 0 and 360 and a direction abbreviation (N, S, E, W, NE, NW, SE, SW):  
- from_adjacent_id_1
- from_adjacent_id_2
- from_adjacent_id_3
- from_adjacent_id_4
- to_adjacent_id_1
- to_adjacent_id_2
- to_adjacent_id_3
- to_adjacent_id_4
- direction_float_field
- direction_text_field

3. obtain_adjacent_values.py - adds eight fields to hold results pulled from each of the following source fields: OWNER, PIPE_TYPE (pipe material), ASB_DATE e.g From_Owner_1, From_Owner_2, To_Owner_1, To_Owner_2, etc (with suffixes 1-4),; populates as many of those fields as possible

4. assign_missing_values_from_adjacent.py - if they don't already exist, adds fields 'As_Built_Date_Source' and 'Pipe_Type_Source'; assigns values from fields created and populated by obtain_adjacent_values.py to original fields 'ASB_DATE' and 'PIPE_TYPE' and updates 'As_Built_Date_Source' and 'Pipe_Type_Source' with explanations as to the source of each value e.g. 'Adjacency From-As-Built-Date (Round 1)'. This script can be run in succession to continue to infer values based on inferred values - before doing this, the ADJACENCY_ROUND environment variable should be set to an integer value greater than 1.


### Sewer Update Process (Jan 2026)

#### As-Built Dates and Material Types (PIPE_TYPE)
See the section above for explanations on the script referenced at some of the steps below. If no script is mentioned for a given step, that step was performed manually in ArcGIS Pro.
1. Assign as-built dates using project numbers - dates originate from 'project table' holding data from Laserfiche ( assign_dates_from_projects.py) 
2. Assign accept dates using project numbers - dates originate from 'project table' holding data from Laserfiche (occurs when running assign_dates_from_projects.py in step 1)
3. Assign dates using a spatial join with 'Construction Project Boundaries' layer (as well as a relational join with the 'project table')
4. Assign dates using a spatial join with the 'Subdivision Average Age' layer - if the 'MinBuilt' date was 1970 or more recent and the size was 15 inches or less, the date of Jan 1 of that year was used (for the few (6-8) that were more than 15 inches, they were populated manually if the dates seemed to fit - otherwise, they were left null)
5. Modify all instances in input feature class where PIPE_TYPE (material type) equals zero - set all values to null.
6. Assign material values using 1986 rule (explain this)
7. Assign both as-built dates and material types using adjacency inference based on multiple segments connected to each endpoint (obtain_adjacent_values.py and assign_missing_values_from_adjacent.py) 
8. ?Use 1986 rule again on material types using dates assigned by adjacency inference? (do this and explain to ULM)
9. Repeat steps 7 and 8 for round 2, 3...? (assign_missing_values_from_adjacent.py - 'obtain_adjacent_values.py' does not need to be run again in this case)

## Output

After the script is run, the output feature class can be found in the same geodatabase as the input feature class but will have the wkid appended to it e.g. 'input_feature_class_2277'

## Post-Processing

After the script has been run, the following are recommended:

1. Spot-checks of the direction values - check a few locations to ensure that the correct bearing and text direction are found in the respective fields. This can be done using a version of the sanitary sewer lines data styled with direction arrows. Though manual intervention has not been needed for the direction values so far, some of the results should still be checked.
2. Population of the original material field ('PIPE_TYPE' field in the original run of the script) based on the values in the new fields - as of June 6, 2025, this is not done in the script, but the steps below should either be added to the existing script or to a new script. In order to avoid issues with modifying an existing domain, it may be necessary to export the feature class produced by the script to a separate (new) geodatabase before attempting to edit the original material field. Note: all SQL statements below (e.g. steps 1 and 3 below) are for use in the SQL option of 'Select by Attributes' in ArcGIS Pro

The steps below involve the material fields. The two sets of 16 steps could be combined into a single set of 16 by wrapping each SQL statements in parentheses and connecting them with 'OR'. In each set of 16 steps below, the first two steps must be done first - the order of the remaining steps does not matter (and note that the order of steps 3-16 is different between the two sets below).

For cases where the original material field (PIPE_TYPE) should be updated and the From_Material and To_Material values match:
1. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND From_Material = To_Material` 
2. Using 'Calculate Field', set Material_Source equal to ‘Adjacency’ for the selected records
3. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND (From_Material = To_Material) AND From_Material = 'Unknown'` 
4. Using 'Calculate Field', set PIPE_TYPE equal to 0
5. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND (From_Material = To_Material) AND From_Material = 'Ductile Iron'`
6. Using 'Calculate Field', set PIPE_TYPE equal to 4
7. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND (From_Material = To_Material) AND From_Material = 'Cast Iron'`
8. Using 'Calculate Field', set PIPE_TYPE equal to 3
9. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND (From_Material = To_Material) AND From_Material = 'PVC'` 
10. Using 'Calculate Field', set PIPE_TYPE equal to 1
11. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND (From_Material = To_Material) AND From_Material = 'RCP'`
12. Using 'Calculate Field', set PIPE_TYPE equal to 2
13. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND (From_Material = To_Material) AND From_Material = 'VCP'` 
14. Using 'Calculate Field', set PIPE_TYPE equal to 5
15. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND (From_Material = To_Material) AND From_Material = 'R.C.C.P'`
16. Using 'Calculate Field', set PIPE_TYPE equal to 6

For cases where the original material field (PIPE_TYPE) should be updated where either From_Material or To_Material is not null and the other (From_Material or To_Material) is null (visually, resembles a dead-end situation but flow is away from a starting point) - in other words, a segment with unknown material is adjacent only to a single segment with known material:
1. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND ((From_Material IS NULL AND To_Material IS NOT null) OR (To_Material IS NULL AND From_Material IS NOT null))`
2. Using 'Calculate Field', set Material_Source equal to ‘Adjacency’ for the selected records
3. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND ((From_Material IS NULL AND To_Material IS NOT null) OR (To_Material IS NULL AND From_Material IS NOT null)) AND (From_Material = 'R.C.C.P' OR To_Material = 'R.C.C.P')`
4. Using 'Calculate Field', set PIPE_TYPE equal to 6
5. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND ((From_Material IS NULL AND To_Material IS NOT null) OR (To_Material IS NULL AND From_Material IS NOT null)) AND (From_Material = 'VCP' OR To_Material = 'VCP')` 
6. Using 'Calculate Field', set PIPE_TYPE equal to 5
7. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND ((From_Material IS NULL AND To_Material IS NOT null) OR (To_Material IS NULL AND From_Material IS NOT null)) AND (From_Material = 'RCP' OR To_Material = 'RCP')`
8. Using 'Calculate Field', set PIPE_TYPE equal to 2
9. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND ((From_Material IS NULL AND To_Material IS NOT null) OR (To_Material IS NULL AND From_Material IS NOT null)) AND (From_Material = 'PVC' OR To_Material = 'PVC')` 
10. Using 'Calculate Field', set PIPE_TYPE equal to 1
11. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND ((From_Material IS NULL AND To_Material IS NOT null) OR (To_Material IS NULL AND From_Material IS NOT null)) AND (From_Material = 'Cast Iron' OR To_Material = 'Cast Iron')` 
12. Using 'Calculate Field', set PIPE_TYPE equal to 3
13. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND ((From_Material IS NULL AND To_Material IS NOT null) OR (To_Material IS NULL AND From_Material IS NOT null)) AND (From_Material = 'Ductile Iron' OR To_Material = 'Ductile Iron')`
14. Using 'Calculate Field', set PIPE_TYPE equal to 4
15. `(PIPE_TYPE IS NULL Or PIPE_TYPE = 0) AND ((From_Material IS NULL AND To_Material IS NOT null) OR (To_Material IS NULL AND From_Material IS NOT null)) AND (From_Material = 'Unknown' OR To_Material = 'Unknown')`
16. Using 'Calculate Field', set PIPE_TYPE equal to 0

Following these steps, the portion of the script that modifies the material fields should be re-run, but the input feature class fed to the script will be the feature class modified in the two sets of 16 steps above.

The output feature class of that second run of the script that modifies the material fields will then be modified using the sets of 16 steps above. 

This process can be repeated a few times (which is why the 16 steps of SQL/Calculate-Field operations should be scripted). Each time the process is run, however, the output feature class should be spot-checked for accuracy.
