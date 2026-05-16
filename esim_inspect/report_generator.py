from jinja2 import Template
import os

class ReportGenerator:

    def __init__(self, components, report, project_path,sch_file):
        self.components = components
        self.report = report
        self.project_path = project_path
        self.sch_file = sch_file
    
    # def export_schematic_image(self,sch_path, output_path):
    #     subprocess.run([
    #         "kicad-cli",
    #         "sch", "export", "svg",
    #         sch_path,
    #         "-o", output_path
    #     ])

    def get_svg_path(self, output_dir):
        for file in os.listdir(output_dir):
            if file.endswith(".svg"):
                return os.path.join(output_dir, file)
        return None

    def generate(self):

        template_path = os.path.join(os.path.dirname(__file__), "template.html")

        with open(template_path) as f:
            template = Template(f.read())

        output_image_path = os.path.join(self.project_path,"ckt_diagram")
        os.makedirs(output_image_path, exist_ok=True)
        # self.export_schematic_image(self.sch_file, output_image_path)
        svg_path = self.get_svg_path(output_image_path)
        if svg_path:
            relative_svg = os.path.relpath(svg_path, self.project_path)
        else:
            relative_svg = None
        # relative_svg = os.path.relpath(svg_path, self.project_path)
        # self.export_schematic_image(self.sch_file,output_image_path)
        
        html = template.render(
            components=self.components,
            report=self.report,
            circuit_diagram = relative_svg
        )

        output_path = os.path.join(self.project_path, "design_report.html")

        with open(output_path, "w") as f:
            f.write(html)

        return output_path