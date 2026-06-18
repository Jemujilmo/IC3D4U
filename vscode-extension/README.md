# IC3D4U FreeCAD Agent — VS Code Chat Participant

Type `@freecad` in GitHub Copilot Chat to generate and modify FreeCAD parts using natural language.

## Requirements
- VS Code 1.90+ with GitHub Copilot
- LM Studio running locally (default: `http://localhost:1234`)
- FreeCAD 1.x with the watcher macro running

## Usage
```
@freecad make a 50x30x10mm mounting bracket with 4 bolt holes
@freecad add a 5mm fillet to the top edges
```

## Configuration
Open **Settings → IC3D4U FreeCAD Agent** to change the LM Studio URL, model name, or FreeCAD macro directory.
