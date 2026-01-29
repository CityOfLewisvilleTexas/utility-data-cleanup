# Clean Utility Data

A series of scripts to:
1. snap line endpoints to nearby point features within a specified distance/tolerance
2. add flow direction to the attribute table of a copy of a line feature layer
3. add new fields to the attribute tables of copies of line or point feature layers containing information on numbers of connected features and specified attributes of features adjacent to a given feature
4. assign attributes (owner, as-built dates, and material types) based on multiple approaches including adjacency inference (see details below)

## Overview

TODO - remove section if unused

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
3. See instructions below as well as docstrings and comments for explanations of parameters

The scripts can be run as a standalone Python script from a terminal (`python path/to/script.py` or `propy path/to/script.py` if using the 'propy' environment provided with ArcGIS Pro).

### Script Sequence and Outputs

#### Sewer Lines (and probably Water Lines)
1. snap_lines_to_points.py - snaps line segments to point features within a given tolerance 

2. assign_dates_from_projects.py - assigns as-built dates and 'accept dates' from a list of projects from Laserfiche - if a single project contains multiple date values, the most commonly-occuring value (mode) is assigned; adds field 'As_Built_Date_Source' and updates field with either 'Project As-Built Date' or 'Project Accept Date'

3. get_flow_direction.py - adds four fields to hold id's of adjacent segments on either side of each segment, populates as many of those fields as possible; also adds fields to hold direction/bearing as both a value between 0 and 360 and a direction abbreviation (N, S, E, W, NE, NW, SE, SW):  
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

4. obtain_adjacent_values.py - adds eight fields to hold results pulled from each of the following source fields: OWNER, PIPE_TYPE (pipe material), ASB_DATE e.g From_Owner_1, From_Owner_2, To_Owner_1, To_Owner_2, etc (with suffixes 1-4),; populates as many of those fields as possible

5. assign_missing_values_from_adjacent.py - if they don't already exist, adds fields 'As_Built_Date_Source' and 'Pipe_Type_Source'; assigns values from fields created and populated by obtain_adjacent_values.py to original fields 'ASB_DATE' and 'PIPE_TYPE' and updates 'As_Built_Date_Source' and 'Pipe_Type_Source' with explanations as to the source of each value e.g. 'Adjacency From-As-Built-Date (Round 1)'. This script can be run in succession to continue to infer values based on inferred values - before doing this, the ADJACENCY_ROUND environment variable should be set to an integer value greater than 1.


### Sewer Update Process (Jan 2026)

#### As-Built Dates and Material Types (PIPE_TYPE)
See the section above for explanations on the script referenced at some of the steps below. If no script is mentioned for a given step, that step was performed manually in ArcGIS Pro. The steps below are designed to be carried out on a local copy (gdb feature class) of the authoritative feature layer.

##### Preparation
1. Remove or correct invalid values in the as-built date field ('ASB_DATE') of the local feature class 
2. Build 'project table' holding project numbers from Laserfiche and fields for 'As-Built Date' and 'Accept Date' - search Google Drive for 'As-Builts from Laserfiche.sql' and save output in a csv file (.sql file was not committed to repo as script contains full paths). Copy csv file to 'csv' directory in repo.
3. Export attribute table of local input feature class to a csv file and copy file to 'csv' directory in repo
3. Snap lines to points if desired


##### Inference/Assignment of Values
1. Assign as-built dates using project numbers - dates originate from 'project table' holding data from Laserfiche (assign_dates_from_projects.py) - 
2. Assign accept dates using project numbers - dates originate from 'project table' holding data from Laserfiche (occurs when running assign_dates_from_projects.py in step 1)
3. Assign dates using a spatial join with 'Construction Project Boundaries' layer (as well as a relational join with the 'project table')
4. Assign dates using a spatial join with the 'Subdivision Average Age' layer - if the 'MinBuilt' date was 1970 or more recent and the size was 15 inches or less, the date of Jan 1 of that year was used (for the few (6-8) that were more than 15 inches, they were populated manually if the dates seemed to fit - otherwise, they were left null)
5. Modify all instances in input feature class where PIPE_TYPE (material type) equals zero - set all values to null.
6. For sewer lines only (not water lines), assign material values if as-builts dates are on or after 1986 and size is 18 inches or less
7. Add and populate fields for flow direction (get_flow_direction.py) - creates a new feature class using the original name with suffix of spatial reference id e.g. 'input_fc_2277'
8. If necessary, export the output of the previous step to a new feature class using the desired spatial reference (4326 was used)
9. For each segment, add adjacent segments' values from fields OWNER, ASB_DATE, MATERIAL (obtain_adjacent_values.py - run script three separate times with three different values for ATTRIBUTE_MODE: OWNER, MATERIAL, and DATE) TODO: add option for 'ALL'
10. Assign both as-built dates and material types using adjacency inference based on multiple segments connected to each endpoint (assign_missing_values_from_adjacent.py) 
11. For sewer lines only (not water lines), repeat step 6 using dates assigned by adjacency inference
12. Repeat previous 2-3 steps (previous 3 for sewer, only steps 9-10 for water) for round 2, 3, etc (re-run 'obtain_adjacent_values.py' for MATERIAL and DATE, then run assign_missing_values_from_adjacent.py)
