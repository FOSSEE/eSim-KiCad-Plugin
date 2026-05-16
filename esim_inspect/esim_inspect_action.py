import pcbnew
import wx
import os
import webbrowser
import sys

sys.path.append(os.path.dirname(__file__))

try:
    # Windows CASE
    from .schematic_pareser import Extract_Information
    from .topology_builder import TopologyBuilder
    from .design_analyzer import DesignAnalyzer
    from .report_generator import ReportGenerator
except ImportError:
    # Linux CASE
    from schematic_pareser import Extract_Information
    from topology_builder import TopologyBuilder
    from design_analyzer import DesignAnalyzer
    from report_generator import ReportGenerator

class ESimInspectPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "eSim-Inspect"
        self.category = "Design Review"
        self.description = "Generate a design review report"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "Rg.png")

    def Run(self):
        board = pcbnew.GetBoard()

        board_file = board.GetFileName()

        project_path = os.path.dirname(board_file)
        # wx.MessageBox(project_path,"Project path")

        project_name = os.path.splitext(os.path.basename(board_file))[0]
        # wx.MessageBox(project_name,"Project name")

        sch_file = os.path.join(project_path, project_name + ".kicad_sch")

        if os.path.exists(sch_file):

            with open(sch_file,'r',encoding="utf-8") as f:
                sch_data = f.read()       
                Parsed_Info = Extract_Information(sch_data)
                components = Parsed_Info.find_components()
                wires = Parsed_Info.get_wires()
                symbol_pins = Parsed_Info.extract_symbol_pins()

                pin_positions = Parsed_Info.get_absolute_pins(components, symbol_pins)

                # wx.MessageBox(str(components),"INFO")     
                # wx.MessageBox(str(wires),"Wires INFO")     
                
                # wx.MessageBox(str(pin_positions), "Pin Positions")

                topo = TopologyBuilder(components, wires)
                graph = topo.build_graph(pin_positions)

                # wx.MessageBox(str(list(graph.edges())), "Graph Edges")

                # with open('Parsed_sch.txt','w') as f:
                #     f.write(sch_data)
                with open(os.path.join(project_path,'Parsed_sch.txt'),'w') as f:
                    f.write(sch_data)

                DA = DesignAnalyzer(components,graph,wires)
                component_graph = topo.build_component_graph(graph)
                report = DA.da_report() 
                
                generator = ReportGenerator(components, report, project_path,sch_file)
                report_path = generator.generate()

                import webbrowser
                webbrowser.open(report_path)

                # with open('checks.txt','w') as f:
                #     f.write(str(pin_positions) +"\n\n" + str(component_graph.nodes) + '\n\n'+ str(component_graph.edges())+ '\n\n' + str(graph.edges()) + '\n\n' + str(report) )
                    # f.write(str(pin_positions) +"\n" + str(graph.edges()) + str(issues) + str(missing_values) + str(missing_refs) + str(spice_chck))
        else:
            wx.MessageBox("sch_file Missing","sch_file status")
        
                

        
        # wx.MessageBox(str(components),"Comps")
            # wx.MessageBox(sch_data,"Sch file data")
            # wx.MessageBox(str(symbol_blocks),"SYmbols")
            


ESimInspectPlugin().register()

