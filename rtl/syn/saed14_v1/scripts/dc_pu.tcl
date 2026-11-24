# dc_pu.tcl -- DC synthesis of one pimdb PU variant (or the per-channel decoder) to SAED14 RVT tt0p8v25c.
# cwd = job dir.  Env: TOP (pu | pu_decoder), PARAMS ("HAS_JOIN=1,HAS_SETSEL=1,HAS_XREG=1" or empty), MODE (flat|hier),
#   PERIOD_NS (2.284 = one 4-tCK command slot), SRC (space-separated .sv files), DB (base + cg .db).
# Timing model = VLA_LPDDR_AiM_RTL run 2 (FIXES #8): zero wire load, high_fanout_net_threshold 0, max_transition 0.2 ns,
#   max_capacitance 0.05 pF, a library buffer driving every data input, 4x its input-pin load on every output,
#   zero input / output delay, ideal clock, no uncertainty.  compile_ultra (no retime, no clock gating).
proc envv {n {d ""}} { if {[info exists ::env($n)] && $::env($n) ne ""} { return $::env($n) }; return $d }
set top [envv TOP]; set params [envv PARAMS]; set mode [envv MODE flat]
set per [envv PERIOD_NS 2.284]; set src [envv SRC]; set dbs [envv DB]
file mkdir rpt out
set_host_options -max_cores 4
set libdirs {}; foreach d $dbs { lappend libdirs [file dirname $d] }
set_app_var search_path [concat . [lsort -unique $libdirs] [get_app_var search_path]]
set_app_var target_library $dbs
set_app_var synthetic_library dw_foundation.sldb
set_app_var link_library [concat * $dbs dw_foundation.sldb]
catch { set_app_var auto_wire_load_selection false }
catch { set_app_var high_fanout_net_threshold 0 }

define_design_lib WORK -path ./work
if {![analyze -format sverilog $src]} { puts "DC_ERROR analyze"; exit 4 }
if {$params ne ""} { set ok [elaborate $top -parameters $params] } else { set ok [elaborate $top] }
if {!$ok} { puts "DC_ERROR elaborate"; exit 4 }
# elaborate leaves the (parameterized) top as current_design
if {![link]} { puts "DC_ERROR link"; exit 4 }
redirect rpt/check_design.rpt { check_design }
set design [get_object_name [current_design]]
puts "DC_DESIGN $design"

# library time unit: SAED14 is ns (checked below; period given in ns)
set lu ""; redirect -variable lu { report_units }
if {[regexp -nocase {Time_unit\s*:\s*(\S+)} $lu -> tu]} { puts "DC_TIME_UNIT $tu" }

create_clock -name clk -period $per [get_ports clk]
set din [remove_from_collection [all_inputs] [get_ports clk]]
set_input_delay 0 -clock clk $din
set_output_delay 0 -clock clk [all_outputs]
set_max_transition 0.2 [current_design]
set_max_capacitance 0.05 [current_design]
set_max_fanout 24 [current_design]
# driving cell / output load: the smallest non-inverting buffer of the base library
set buf ""; set ba 1e9
set baselib [file rootname [file tail [lindex $dbs 0]]]
foreach_in_collection lc [get_lib_cells $baselib/*BUF*] {
    set n [get_object_name $lc]
    if {[string match *CK* [file tail $n]] || [string match *_cg_* $n]} { continue }
    set a [get_attribute $lc area]; if {$a < $ba} { set ba $a; set buf $n }
}
set bpin_in ""; set bpin_out ""
foreach_in_collection p [get_lib_pins $buf/*] {
    set d [get_attribute $p pin_direction]
    if {$d eq "in"} { set bpin_in [file tail [get_object_name $p]] } elseif {$d eq "out"} { set bpin_out [file tail [get_object_name $p]] }
}
set_driving_cell -lib_cell [file tail $buf] -library [file dirname $buf] -pin $bpin_out $din
set cin [get_attribute [get_lib_pins $buf/$bpin_in] capacitance]
set_load [expr {4.0 * $cin}] [all_outputs]
puts "DC_DRIVING_CELL $buf $bpin_in->$bpin_out load [expr {4.0 * $cin}]"

if {$mode eq "flat"} {
    ungroup -all -flatten
    compile_ultra -no_autoungroup
} else {
    compile_ultra -no_autoungroup
}
change_names -rules verilog -hierarchy
redirect rpt/area.rpt        { report_area -nosplit }
redirect rpt/area_hier.rpt   { report_area -nosplit -hierarchy }
redirect rpt/qor.rpt         { report_qor }
redirect rpt/timing_max.rpt  { report_timing -delay_type max -max_paths 5 -nosplit -input_pins -nets }
redirect rpt/timing_min.rpt  { report_timing -delay_type min -max_paths 3 -nosplit }
redirect rpt/constraint.rpt  { report_constraint -all_violators -nosplit }
redirect rpt/reference.rpt   { report_reference -nosplit }
redirect rpt/power_dc.rpt    { report_power -nosplit }
set p [get_timing_paths -delay_type max -max_paths 1]
puts "DC_WNS [get_attribute $p slack]"
puts "DC_AREA [get_attribute [current_design] area]"
puts "DC_NREG [sizeof_collection [all_registers]]"
write -format verilog -hierarchy -output out/net.v
write_sdc out/design.sdc
puts "DC_DONE"
exit 0
