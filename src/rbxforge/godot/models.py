from dataclasses import dataclass, field


@dataclass(frozen=True)
class GodotFile:
    path: str
    kind: str
    size: int
    content: str = ""


@dataclass(frozen=True)
class GodotScene:
    path: str
    nodes: list[str] = field(default_factory=list)
    external_resources: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GodotProject:
    root: str
    name: str
    files: list[GodotFile] = field(default_factory=list)
    scenes: list[GodotScene] = field(default_factory=list)
