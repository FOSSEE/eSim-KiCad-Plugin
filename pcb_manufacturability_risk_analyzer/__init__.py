try:
    from .plugin import PCBAnalyzer
    PCBAnalyzer().register()
    print("Plugin registered successfully")
except Exception as e:
    print(f"Failed to register plugin: {e}")
