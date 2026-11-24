# pt_pu.tcl -- PrimeTime sign-off timing + (optional) PrimePower time-based power of one DC netlist.
# cwd = job dir.  Env: TOP (netlist top module), NET, SDC (DC's write_sdc), DB (base + cg .db), VCD (optional: gate-level
#   VCD whose scope tb_pu/dut is the design), PERIOD_NS (power waveform interval = one clock).
# Timing model = DC's: zero wire load (auto_wire_load_selection false), ideal clock (no clock tree), no uncertainty.
# Markers: PT_WNS_MAX, PT_WNS_MIN, PT_NVIOL_MAX, PT_NVIOL_MIN, PT_ANNOT <annotated %>, PT_POWER <total int switch leak>
#   (W), PT_DONE.
proc envv {n {d ""}} { if {[info exists ::env($n)] && $::env($n) ne ""} { return $::env($n) }; return $d }
set top [envv TOP]; set net [envv NET]; set sdc [envv SDC]; set dbs [envv DB]; set vcd [envv VCD]
set per [envv PERIOD_NS 2.284]
file mkdir rpt
set libdirs {}; foreach d $dbs { lappend libdirs [file dirname $d] }
set_app_var search_path [concat . [lsort -unique $libdirs]]
set_app_var link_path [concat * $dbs]
set_app_var auto_wire_load_selection false
if {$vcd ne ""} { set_app_var power_enable_analysis true; set_app_var power_analysis_mode time_based }
read_verilog $net
current_design $top
if {![link_design $top]} { puts "PT_ERROR link"; exit 4 }
read_sdc $sdc
update_timing -full
proc wns {t} { set p [get_timing_paths -delay_type $t -max_paths 1]; if {[sizeof_collection $p] == 0} { return NA }; return [get_attribute $p slack] }
proc nviol {t} { return [sizeof_collection [get_timing_paths -delay_type $t -max_paths 100000 -nworst 1 -slack_lesser_than 0]] }
puts "PT_WNS_MAX [wns max]"
puts "PT_WNS_MIN [wns min]"
puts "PT_NVIOL_MAX [nviol max]"
puts "PT_NVIOL_MIN [nviol min]"
redirect rpt/pt_timing_max.rpt { report_timing -delay_type max -max_paths 5 -nosplit -input_pins -nets }
redirect rpt/pt_timing_min.rpt { report_timing -delay_type min -max_paths 3 -nosplit }
redirect rpt/pt_constraint.rpt { report_constraint -all_violators -nosplit }

if {$vcd ne ""} {
    if {![file exists $vcd]} { puts "PT_ERROR missing $vcd"; exit 5 }
    read_vcd -strip_path tb_pu/dut $vcd
    set_power_analysis_options -waveform_interval $per -waveform_format out -waveform_output pwr_wave
    redirect rpt/switching.rpt { report_switching_activity -list_not_annotated -base_clock clk }
    set sa ""; redirect -variable sa { report_switching_activity }
    puts "PT_ANNOT_RPT_BEGIN"; puts $sa; puts "PT_ANNOT_RPT_END"
    if {![update_power]} { puts "PT_ERROR update_power"; exit 6 }
    redirect rpt/power.rpt       { report_power -nosplit -verbose }
    redirect rpt/power_group.rpt { report_power -nosplit -groups {clock_network register combinational sequential} }
    redirect rpt/power_cells.rpt { report_power -nosplit -cell_power -sort_by total_power -nworst 30 }
    set tot [get_attribute [current_design] total_power]
    set int [get_attribute [current_design] internal_power]
    set sw  [get_attribute [current_design] switching_power]
    set lk  [get_attribute [current_design] leakage_power]
    puts "PT_POWER $tot $int $sw $lk"
}
puts "PT_DONE"
exit 0
