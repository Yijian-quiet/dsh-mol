"""chemcore —— 本地优先的化学基础工具核心。

设计原则
--------
1. **零网络**：全部计算在本进程完成（RDKit），不依赖任何外部服务。
2. **零额外依赖**：只用 RDKit（+其自带的 Pillow）。测试也不需要 pytest。
3. **失败要说人话**：RDKit 不抛异常、只写英文日志；这里负责翻译成分级诊断。
4. **不许静默丢数据**：批量接口逐条报告失败，而不是过滤掉了事。

对外 API：
    check / canonicalize          —— 校验与规范化
    properties                    —— 性质计算
    draw / draw_grid              —— 画分子
    convert / convert_many        —— 格式互转
    standardize / dedupe          —— 结构标准化与去重
    batch_clean / read_smiles_column —— 批量清洗
"""

from .batch import batch_clean, read_smiles_column
from .convert import FORMATS, convert, convert_many, sniff
from .draw import draw, draw_grid, out_dir
from .props import properties
from .search import find_similar, similarity, substructure_match
from .standardize import dedupe, standardize
from .validate import CheckResult, Diagnostic, canonicalize, check

__version__ = "0.0.1"

__all__ = [
    "CheckResult", "Diagnostic", "check", "canonicalize",
    "properties",
    "draw", "draw_grid", "out_dir",
    "convert", "convert_many", "sniff", "FORMATS",
    "standardize", "dedupe",
    "substructure_match", "similarity", "find_similar",
    "batch_clean", "read_smiles_column",
    "__version__",
]
