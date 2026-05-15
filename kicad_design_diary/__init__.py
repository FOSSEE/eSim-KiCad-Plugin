import pcbnew


class DesignDiaryPlugin(pcbnew.ActionPlugin):

    def defaults(self):
        self.name = 'KiCad Design Diary'
        self.category = 'Design History'
        self.description = (
            'Complete design version control — tracks changes, '
            'runs simulations, supports rollback. Git for circuits.'
        )
        self.show_toolbar_button = True
        self.icon_file_name = ''

    def Run(self):
        from kicad_design_diary.plugin import DesignDiaryPlugin as Core
        Core().Run()


DesignDiaryPlugin().register()