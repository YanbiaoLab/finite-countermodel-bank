# Finite Countermodel Bank

[English](#english) | [简体中文](#简体中文)

## English

Finite Countermodel Bank is an emerging collection of finite countermodels: small,
explicit structures that satisfy a stated set of assumptions while falsifying a
target conjecture. The project aims to make these witnesses easy to inspect,
reproduce, cite, and reuse in logic research, automated reasoning, and teaching.

> [!NOTE]
> This repository is in its initial setup stage. It does not contain countermodel
> records or a finalized data schema yet.

### What a record should contain

Each countermodel should eventually provide enough information for an independent
reader or tool to reconstruct and verify it:

| Field | Purpose |
| --- | --- |
| Identifier | A stable, unique name for the record |
| Logical setting | The logic, semantics, and vocabulary in use |
| Assumptions | The axioms or premises satisfied by the structure |
| Falsified statement | The conjecture that fails in the structure |
| Finite domain | The carrier set and its cardinality |
| Interpretation | Values of constants, functions, and relations |
| Witness | A valuation or element demonstrating the failure, when applicable |
| Verification | Reproduction instructions and tool/version information |
| Provenance | Author, source, date, and relevant references |

The machine-readable format and validation rules will be documented before the
first stable dataset release.

### Planned organization

As the collection grows, the repository is expected to separate countermodel data,
schemas, validation tools, and tests. The concrete directory layout will be added
once the record format is agreed upon.

### Contributing

Ideas, corrections, and countermodel submissions are welcome. While the schema is
still being designed, please open an issue before preparing a large contribution.
A useful submission should include:

- a precise statement of the assumptions and the falsified conjecture;
- a complete description of the finite structure;
- enough information to reproduce or independently check the result; and
- provenance and citation details for material derived from another source.

### Citing the repository

Until a versioned release and citation file are available, cite the repository URL
and the commit hash used in your work.

### License

No license has been selected yet. Until a license file is added, no permission to
reuse or redistribute the repository contents is granted by default.

## 简体中文

Finite Countermodel Bank（有限反模型库）是一个正在建设的有限反模型集合。
有限反模型是规模有限且可明确描述的结构：它满足给定的假设或公理，同时使目标猜想为假。
本项目希望让这类反例便于查阅、复现、引用，并可用于逻辑研究、自动推理和教学。

> [!NOTE]
> 仓库目前处于初始化阶段，尚未收录反模型，也尚未确定最终的数据格式。

### 计划收录的信息

每条反模型记录应尽可能包含以下内容：

- 稳定且唯一的标识符；
- 所采用的逻辑、语义和语言签名；
- 结构所满足的假设或公理；
- 在该结构中不成立的目标命题；
- 有限论域及其大小；
- 常量、函数和关系的完整解释；
- 必要时给出使目标命题失败的赋值或元素；
- 验证方法、工具名称及版本；
- 作者、来源、日期和相关文献。

机器可读格式和验证规则将在首个稳定数据集发布前补充说明。

### 参与贡献

欢迎提交想法、修正和反模型。在数据规范仍处于设计阶段时，如需进行较大规模的贡献，
建议先创建 issue 讨论。提交内容应准确说明假设与目标命题，完整描述有限结构，提供可复现
或可独立检查的信息，并注明数据来源与引用。

### 引用与许可证

在正式版本和引用文件发布前，请在引用时注明仓库地址与所使用的 commit hash。
仓库目前尚未选择许可证；在添加许可证文件之前，默认不授予复制、修改或再分发权限。
