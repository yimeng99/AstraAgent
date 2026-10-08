"""子模块通过 __all__ 声明工具，父包统一导出供主 Agent 注册。"""

from importlib import import_module
from pkgutil import iter_modules

__all__: list[str] = []

for _info in sorted(iter_modules(__path__), key=lambda item: item.name):
    if _info.name.startswith("_"):
        continue
    _module = import_module(f"{__name__}.{_info.name}")
    for _name in getattr(_module, "__all__", ()):
        # 同名工具不能静默覆盖，否则注册结果取决于模块加载顺序。
        if _name in __all__ or _name in globals():
            raise ValueError(f"工具导出名称重复或冲突：{_name}")
        globals()[_name] = getattr(_module, _name)
        __all__.append(_name)

__all__.sort()
