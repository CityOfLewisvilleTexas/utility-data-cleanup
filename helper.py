import arcpy

# helper functions that may be used to avoid returning to a state of feature class at a given step

def reset_field_values(input_fc, field_list, existing_value):
    for field in field_list:
        #select features from the given field with the given existing value
        arcpy.management.SelectLayerByAttribute(
            in_layer_or_view=input_fc,
            selection_type="NEW_SELECTION",
            where_clause=f"{field} = {existing_value}",
            invert_where_clause=None
        )
        selected_count = arcpy.management.GetCount(input_fc)
        # set values in given field back to null (None) for selected features
        arcpy.management.CalculateField(
            in_table=input_fc,
            field=field,
            expression="None",
            expression_type="PYTHON3",
            code_block="",
            field_type="TEXT",
            enforce_domains="NO_ENFORCE_DOMAINS"
        )
        print(f'{selected_count} values set back to null for {field}')

# sample call
reset_field_values("sewer_lines_20260108_1153_to_receive_values_using_multiple_adjacent_segments_after_using_1986_rule_no_zero_pipe_type",
                   ["From_Material_1", "From_Material_2", "From_Material_3", "From_Material_4", 
                    "To_Material_1", "To_Material_2", "To_Material_3", "To_Material_4"],
                    existing_value=0)