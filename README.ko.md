<div align="center">

# dsh-mol · 화학 워크벤치

**AI agent의 채팅창 옆에, 분자를 그릴 수 있는 캔버스와 로컬 RDKit 워크벤치를.**

구조를 그리고 → 한 번 클릭 → 분자식/분자량/logP/TPSA/약물 유사성/구조 경고가 **그 자리에서 계산된다** →
그 구조를 대화에 넘기면 agent가 이어서 설명한다.

순수 RDKit. **네트워크 없음, API 키 없음, 외부 서비스 없음.** stdio MCP 서버로 Claude Code / Codex 등에서 직접 호출할 수도 있다.

[![ci](https://github.com/Yijian-quiet/dsh-mol/actions/workflows/ci.yml/badge.svg)](https://github.com/Yijian-quiet/dsh-mol/actions/workflows/ci.yml)
[![Awesome DSH Plugin](https://awesome-dsh-plugin.com/badge.svg)](https://awesome-dsh-plugin.com)
[![M8ven Score](https://m8ven.ai/badge/mcp/yijian-quiet/dsh-mol)](https://m8ven.ai/mcp/yijian-quiet/dsh-mol?s=readme)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![tests](https://img.shields.io/badge/tests-71%20passed-brightgreen)
![network](https://img.shields.io/badge/network-none%20required-success)

[中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | **한국어** | [Français](README.fr.md) | [繁體中文](README.zh-TW.md)

<img src="docs/workbench-analyze.png" alt="화학 워크벤치 · 분석 탭" width="820">

</div>

---

## 30초면 파악

| | |
|---|---|
| 🎨 **분자 그리기** | 채팅창 옆 버튼 하나 → Ketcher 캔버스 오버레이. **채팅이 밀려나지 않는다**. 다 그리면 클릭 한 번으로 입력창에 들어간다 |
| ⚡ **즉시 분석** | 분자식, MW, 정확 질량, logP, TPSA, HBD/HBA, 고리 수, Fsp³, 입체 중심 —— 로컬 RDKit이 **그 자리에서** 계산한다. 모델도, LLM도 기다리지 않는다 |
| 💊 **약이 될 만한가** | Lipinski / Veber 항목별 판정, QED, PAINS / BRENK 구조 경고, Murcko 골격 |
| 🧹 **더러운 데이터 응급처치** | 검증(사람의 말로 된 오류 + 문자 위치), 표준화(바뀐 점을 단계별로 기록), 중복 제거, 일괄 정리 |
| 🧭 **역합성** | 탭은 이미 있고 백엔드는 교체 가능(현재는 Retro*). **모델이 설치돼 있지 않으면 설치돼 있지 않다고 솔직히 말하며, 경로를 지어내는 일은 절대 없다** |
| 🔌 **두 가지 사용법** | 그래픽 워크벤치는 사람용. 같은 코어가 MCP를 통해 agent에게도 간다 —— **구현은 하나, 입구는 둘** |

> 배경 하나: npm에 DSH 플러그인이 **618개** 있는 것을 확인했고, 그중 **화학/재료/분자 분야는 0개**다.
> 이 저장소는 그 빈자리를 채우러 왔다.

---

## 빠른 시작

```bash
# 1) 코어 + MCP 어댑터 설치(PyPI에 공개됨)
pip install 'dsh-mol[mcp]'
#    설치가 안 되면 git으로: pip install "dsh-mol[mcp] @ git+https://github.com/Yijian-quiet/dsh-mol.git"

# 2) 플러그인을 DSH profile에 설치(npm 계정 불필요, pnpm이 git 하위 디렉터리를 처리한다)
dsh plugin --profile web add 'github:Yijian-quiet/dsh-mol#path:dsh-bundle'
dsh plugin --profile web add 'github:Yijian-quiet/dsh-mol#path:dsh-ui'   # ← 그래픽 워크벤치

# 3) DSH Web을 열고 입력창 왼쪽의 "워크벤치"를 클릭
```


> ✅ **PyPI에 공개됨**: `pip install 'dsh-mol[mcp]'` (2026-09-26 공개, 설치 후 `dsh-mol-mcp --selftest`로 자체 점검 가능).
> ⏳ **npm에는 아직 없다**. 그래서 플러그인 자체는 여전히 `dsh plugin add github:…`로 설치한다 —— 기능에는 아무 영향이 없다.
>
> ✅ 이 플러그인은 [dsh 플러그인 마켓](https://awesome-dsh-plugin.com)에 등록돼 있다(`dsh-mol#dsh-ui`와
> `dsh-mol#dsh-bundle` 두 건, 분류는 `tools`). 마켓에서 바로 설치해도 된다.

워크벤치를 쓰려면 로컬에 `import rdkit`이 되는 `python3`가 있어야 한다. 캔버스는 [Ketcher](https://github.com/epam/ketcher) 정적 빌드이며, **브라우저 안에서 로컬로 렌더링하고 백엔드를 전혀 거치지 않는다**.

<details>
<summary>명령줄만 쓰거나 다른 MCP 클라이언트를 쓴다면?</summary>

```bash
dsh-mol-mcp --selftest          # 먼저 자체 점검(MCP 클라이언트 불필요)
```

```yaml
# patch를 직접 덧씌운다. stdio 전송, 완전 로컬
- insert:
    - id: dsh-mol
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: chem
        transport: stdio
        command: python3
        args: ['-m', 'dsh_mol_mcp.server']
        env:
          PYTHONPATH: /path/to/dsh-mol/src
          MOL_OUT: /path/to/out
```

도구 이름은 모델 쪽에 `mcp__chem__chem_check_smiles` 같은 형태로 나타난다.
</details>

---

## 워크벤치의 모습

탭은 셋, 분자는 하나:

<table>
<tr>
<td width="33%"><img src="docs/workbench-draw.png" alt="캔버스 탭"><br><b>① 캔버스</b><br>Ketcher 전체 기능 캔버스(오버레이는 드래그할 수 있고 최대화도 된다). "대화에 삽입"은 SMILES를 입력창에 써 넣는다 —— <b>텍스트에는 구조 자체만 들어가고 내부 경로는 끼어들지 않는다</b>.</td>
<td width="33%"><img src="docs/workbench-analyze.png" alt="분석 탭"><br><b>② 분석</b><br>왼쪽에 입력과 버튼, 오른쪽에 숫자. 기본 성질 + 약물 유사성 + 구조 경고 + 골격을 한 번에, 전부 로컬 RDKit이 즉시 계산한다.</td>
<td width="33%"><img src="docs/workbench-retro.png" alt="역합성 탭"><br><b>③ 역합성</b><br>목표 분자 → 다단계 경로. 모델 데이터가 없으면 <b>무엇을 내려받아 어디에 두어야 하는지 알려준다</b>. 계산한 척하지 않는다.</td>
</tr>
</table>

### 그림을 패널 안에 그리지 않는 이유

**그림은 그것을 설명하는 글을 따라가야** 하기 때문이다. 워크벤치 안의 썸네일은 "계산한 것이 이 분자가 맞는지" 확인하는 용도일 뿐이다.
진짜 구조 그림은 agent가 답변 안에 인라인으로 그리고(`read_image`), 바로 옆에 그 분자에 대한 설명이 놓인다.

이 결정은 두 버전이 사용자에게 거절된 끝에 정해졌다:
처음엔 "패널이 본문 영역을 차지해 채팅이 밀려난다"였고, 다음엔 "캔버스 안에 미리보기를 한 장 더 그리는 건 쓸모가 없다"였다.
지금은 **채팅은 원래대로, 워크벤치는 옆에** 있다.

---

## RDKit을 "한 겹 감싸는" 것만으로는 왜 안 되는가

그냥 감싸기만 하면 AI agent에게 세 가지 함정을 안겨주는데, 이 셋은 연구 현장에서 실제로 물어뜯는다:

### 1. RDKit은 파싱에 실패해도 **예외를 던지지 않고** `None`을 돌려준다

실패 이유는 C++ 계층의 stderr에 적힌다. 순진한 래퍼에서는 모델이 속이 빈 `None` 하나만 받고, 어디가 잘못됐는지 전혀 알 수 없다.
이 도구는 RDKit 로그의 경로를 바꿔 잡아내고, **사람의 말로 번역**하며, 짚어낼 수 있으면 **문자 위치**까지 준다:

```jsonc
// chem_check_smiles("C1CC")
{ "level": "error",
  "diagnostics": [{ "code": "unclosed_ring",
                    "message": "环闭合标记没有配对：SMILES 里的成环数字（如 C1...C1）出现次数必须是偶数" }] }

// chem_check_smiles("CC(=O)O)")   ← 닫는 괄호가 하나 많다. 7번째 문자를 가리킨다
{ "level": "error", "position": 7,
  "diagnostics": [{ "code": "extra_paren", "message": "多余的右括号：) 比 ( 多" }] }
```

### 2. `MolFromSmiles("")`가 돌려주는 것은 `None`이 아니라 **원자 0개의 "빈 분자"**다

순진한 구현은 빈 입력을 **적법**하다고 판정한다. 그런데 `"   "`(공백만)는 **또** `None`을 돌려준다 ——
같은 함수, 같은 빈 입력인데 두 가지 행동. 이 도구는 도메인 계층에서 둘 다 한꺼번에 막는다.

### 3. 결과는 "성공/실패"가 아니라 **3단계**다

`[Fe+9]`는 파싱되지만 전하가 터무니없다. 이런 것은 거부가 아니라 **경고**여야 한다:

| level | 의미 |
|---|---|
| `ok` | 깨끗하게 통과 |
| `warn` | 파싱은 되지만 구조가 수상하다(비정상 전하, 의심스러운 방향성…). 이유 포함 |
| `error` | 파싱 실패. 사람의 말로 된 이유 + 짚어낼 수 있는 문자 위치 |

**그리고 일괄 API는 데이터를 조용히 버리지 않는다.** 모든 행에 명확한 귀속이 있고(ok / warn / failed),
실패는 한 건씩 나열된다 —— 연구 데이터에서는 "두 줄이 소리 없이 사라졌다"가 오류보다 훨씬 위험하다.

### 진단 문구는 중국어·영어 두 언어

기본은 중국어. 영어 환경에서는 환경 변수 하나만 설정하면 된다:

```bash
export MOL_LANG=en        # zh(기본) / en
```

> ⚠️ **계약은 `code`이고, 문구가 아니다.** `code`(`unclosed_ring` / `valence` …)는 언어와 무관하며,
> 언어를 바꿔도 `level` / `position` / `canonical`은 **변하지 않는다** —— 이것을 고정하는 전용 회귀 케이스가 있다.

---

## 도구 목록(13개, 모두 완전 로컬)

| 도구 | 역할 |
|---|---|
| `chem_check_smiles` | 검증 + 정규화. 3단계 결과 + 사람의 말로 된 이유 + 문자 위치 |
| `chem_properties` | 분자식 / MW / 정확 질량 / logP / TPSA / HBD / HBA / 고리 수 / 입체 중심 |
| `chem_analyze` | 한 번에 전부: 기본 성질 + 약물 유사성 + 구조 경고 + Murcko 골격 |
| `chem_druglikeness` | Lipinski / Veber 항목별 판정, QED, PAINS / BRENK 구조 경고 |
| `chem_draw_molecule` | 구조 그림 렌더링(PNG/SVG, 원자 번호 표시와 부분 구조 강조 가능). 돌려주는 것은 **파일 경로** |
| `chem_draw_grid` | 여러 분자 그리드(보고서/논문 그림용). 나쁜 항목은 건너뛰되 하나씩 기록한다 |
| `chem_convert` | smiles / inchi / inchikey / mol / sdf / formula 상호 변환 |
| `chem_bioseq` | 펩타이드 / 핵산 서열, HELM 또는 IDT 표기법 → 분자(정규화된 SMILES를 주므로 다른 도구로 이어진다). **kind는 반드시 명시** |
| `chem_standardize` | 탈염 / 금속 제거 / 중화 / 정규화. **바뀐 점을 단계별로 기록** |
| `chem_dedupe` | 정규화된 구조로 중복 제거, 중복 그룹 반환 |
| `chem_substructure_match` | SMARTS 부분 구조 매칭, 원자 인덱스 반환 |
| `chem_similarity` | 지문 유사도(morgan / rdkit / maccs) |
| `chem_batch_clean` | SMILES 한 열을 일괄 정리. 건수 요약 + 실패 목록(CSV 출력 가능) |

워크벤치의 "분석" 탭은 이 도구들과 **같은 `chemcore`를 공유한다** —— "화면에서 하나 계산하고 agent가 다른 걸 계산하는" 어긋남은 없다.

> `chem_core`에는 `python3 -m chemcore.cli`라는 JSON 입구도 있다(JSON 한 줄이 들어가고 JSON 한 줄이 나온다).
> 워크벤치의 즉시 숫자가 여기를 지난다. "AI를 위한 도구"와 "사람을 위한 화면"이 구현 하나를 공유하는 이음매가 이것이다.

## 생체 고분자(펩타이드 / 핵산)는 어떻게 다루는가

Ketcher의 거대 분자 편집기로 그린 펩타이드 / 핵산에는 **SMILES가 없다**. 서열이나 HELM만 있다.
`chem_bioseq`가 그것을 분자로 파싱하고 **정규화된 SMILES**를 돌려준다 —— 그래서 위의 모든 도구(properties / analyze /
draw / convert)가 같은 분자로 계속 계산할 수 있다.

```python
cc.parse_bioseq("GAVL", kind="peptide")            # 펩타이드, 1문자 코드 → C16H30N4O5 / 358.4
cc.parse_bioseq("Gly-Ala-Val", kind="peptide3")    # 펩타이드, 3문자 코드 → 삼펩타이드 C10H19N3O4 / 245.3
cc.parse_bioseq("AUGC", kind="rna")                # RNA → C38H48N15O26P3 / 1223.8
cc.parse_bioseq("ATGC", kind="dna")                # DNA → C39H50N15O22P3 / 1173.8
cc.parse_bioseq("PEPTIDE1{G.A.V.L}$$$$")           # HELM: 접두사가 타입을 선언하므로 auto로 충분하다
```

### 왜 `kind`를 명시해야 하는가

`A/T/G/C`가 **아미노산 문자이면서 동시에 염기 문자**이기 때문이다(Ala/Thr/Gly/Cys ↔ 아데닌/티민/구아닌/시토신).
같은 `ATGC`가 펩타이드로는 `C12H22N4O6S`, RNA로는 `C39H50N15O26P3`, DNA로는 `C39H50N15O22P3` ——
셋 다 전혀 다른 분자인데, RDKit의 `MolFromSequence`는 **기본값으로 펩타이드로만 읽고 아무 오류도 내지 않는다**.

그래서 이 도구의 규칙은 이렇다:

- **맨 서열에는 `kind`를 반드시 명시해야 한다**(`auto`도 마찬가지). 그러지 않으면 곧바로 오류다 ——
  "…이 펩타이드인지 핵산인지 판단할 수 없어 파싱을 거부했다". **호출자 대신 기본값을 골라주지 않는다**:
  잘못 고르면 "화학적으로 완전히 틀렸는데 그 흔적조차 전혀 없는" 상태가 되고, 그게 오류보다 위험하다.
- `auto`에서 확실히 추론할 수 있는 것은 타입 정보를 스스로 가진 **두 가지 표기법뿐**이다: **HELM**(`PEPTIDE1{` / `RNA1{` / `DNA1{` 접두사는 추측이 아니라 **선언**이다)과 **IDT**(당 접두사 `r`/`d` 역시 선언이다). 그 밖의 입력은 `auto`에서 예외 없이 거부한다 —— 맨 서열(`ACGU` / `ATGC` / `GAVL`)에는 타입 정보가 없고 기본값도 주지 않는다.

> 관련된 RDKit 함정 두 가지(둘 다 실측했고, 이 프로젝트는 둘 다 피해 간다): **DNA의 flavor는 3이 아니라 6**
> (3은 "RNA에 5' 인산 캡을 씌운다"는 뜻이라 인산이 하나 더 붙는다). 그리고 **3문자 아미노산 코드는
> RDKit 2023.09.6이 아예 지원하지 않는다** —— `Gly-Ala-Val`을 대소문자 무시 1문자 코드로 읽어
> 9잔기 펩타이드(MW 890.1)로 해석하고 오류를 내지 않는다. 그래서 `peptide3`는 이 계층이 직접 1문자 코드로
> 번역한 뒤 계산한다. 서열 안의 공백도 RDKit은 조용히 여분의 수소로 바꾸므로, 이 계층이 먼저 정규화하고
> 그 변경을 `warnings`에 기록한다.

### IDT 표기법(Ketcher가 핵산을 내보내는 형식)

Ketcher의 거대 분자 편집기에서 핵산을 내보내면 나오는 것이 **IDT 표기법**이다(실측: RNA를 그리면
`rArCrGrTrU/3Phos/`). 잔기에는 당 유형 접두사가 붙고(`r`=리보스, `d`=디옥시, `m`=2′-O-메틸,
`+`=LNA), `/3Phos/` `/5Phos/` 같은 말단 변형도 있다. `chem_bioseq`는 이것을 그대로 받는다 ——
`kind` 값에 `idt`가 늘어난 이유다(`auto`도 알아본다: 당 접두사는 추측이 아니라 **선언**이다).

**다만 무손실일 때만 변환한다.** 당 유형이 하나로 통일돼 있고 변형이 없을 때만 순수 서열로 바꿔
RDKit에 넘긴다. 표현할 수 없는 것이 하나라도 있으면 거부하고 이유를 밝힌다:

```python
cc.parse_bioseq("rArCrGrTrU", kind="idt")         # → RNA ACGTU / MW 1543.997(당 통일·변형 없음 = 무손실)
cc.parse_bioseq("rArCrGrTrU/3Phos/", kind="idt")  # ✗ 거부: 억지로 바꾸면 3′ 인산이 조용히 사라진다(≈79.97 Da)
```

거부할 때는 반드시 무엇 때문인지 짚어 준다:

- 말단/골격 변형: `/3Phos/`, `/5Phos/`, `*`(포스포로티오에이트)
- 비표준 당: `m`(2′-O-메틸), `+`(LNA)
- 당 혼용: `rArCdT`(한 문자열에 리보스와 디옥시 —— RDKit은 한 번에 하나만 표현한다)
- 호출자가 준 `kind`와의 충돌: `rArCrG` + `kind="dna"`(접두사가 선언하는 것은 RNA다)

이유는 위와 같다: 억지 변환은 근사가 아니라 **화학적으로 완전히 틀렸는데 겉보기에는 아무 이상이 없는**
결과를 만든다 —— 분자량이 79.97 Da 가벼운데 화면은 멀쩡해 보인다.

## Python API

```python
import chemcore as cc

cc.check("C1CC").diagnostics[0].message   # '环闭合标记没有配对：…'
cc.properties("CC(=O)Oc1ccccc1C(=O)O")    # {'formula': 'C9H8O4', 'mw': 180.159, …}
cc.analyze("CC(=O)Oc1ccccc1C(=O)O")       # + QED / Lipinski / PAINS 경고 / Murcko 골격
cc.draw("CCO", atom_indices=True)         # {'path': '…/CCO.png', …}
cc.standardize("CC(=O)[O-].[Na+]")        # {'output': 'CC(=O)O', 'changes': [...]}
cc.batch_clean(["CCO", "C1CC"])           # {'ok': 1, 'failed': 1, 'failed_items': [...]}
cc.parse_bioseq("GAVL", kind="peptide")   # 펩타이드/핵산/HELM → 분자 + 정규화 SMILES(kind 필수)
```

## 예제: 지저분한 모노머 표 정리하기

[`examples/monomer_cleanup.py`](examples/monomer_cleanup.py)는 일부러 지저분하게 만든 모노머 표
(같은 분자를 두 가지로 쓴 것, 나트륨 염, 고리가 닫히지 않은 오타, 원자가 초과, 터무니없는 전하)를 가지고
전체 사슬을 돌린다:

```bash
python3 examples/monomer_cleanup.py
```

11건 통과, 1건 경고, 2건 실패라고 보고하고, 중복을 합치고, 탈염과 중화의 각 단계를 차례로 보여주며,
그릴 수 있는 12개 구조를 그리고 건너뛴 2개는 이유와 함께 나열한다.

![일괄 그리기(그림 설명은 중국어)](docs/monomers.png)

## 역합성

역합성 탭의 백엔드는 **교체 가능**하다: 플러그인이 `child_process`로 "stdin에 JSON을 넣고 stdout에서 JSON을 읽는" 프로세스를 띄우며, 기본값은 저장소 안의 Retro* 브리지 스크립트를 가리킨다.

- 백엔드가 **설치되지 않았을** 때: 구조화된 진단(빠진 파일, 어디서 받는지, 어디에 두는지)을 돌려주고 화면은 그것을 그대로 보여준다 ——
  **경로를 지어내지 않고**, "그럴듯해 보이는" 것으로 얼버무리지도 않는다
- 백엔드를 바꾸고 싶다면(AiZynthFinder / 직접 만든 RetroChimera / 소속 그룹의 내부 서버): 같은
  stdin/stdout 프로토콜만 지키고 `retroCommand`를 그쪽으로 돌리면 된다

Retro* 설치(소스 + 모델 데이터, GB 단위)는 **[docs/RETROSYNTHESIS.md](docs/RETROSYNTHESIS.md)** 참고.

## 테스트

```bash
PYTHONPATH=src python3 tests/run_tests.py    # 핵심 케이스 71개(의존성 제로, pytest 불필요)
PYTHONPATH=src python3 tests/mcp_smoke.py    # MCP 프로토콜 수준 스모크(실제로 서버를 띄우고 도구를 호출한다)
bash tests/run_all.sh                        # 위의 둘 + 자체 점검을 한 번에
```

화면은 Playwright 헤드리스로 인수한다(어서션 33개. "워크벤치를 연 뒤에도 채팅을 쓸 수 있는가",
"숫자가 정말 계산된 것인가", "백엔드가 없을 때 경로를 지어내지 않는가"를 덮는다):

```bash
dsh web --port 3081 --no-open > /tmp/chemver.log 2>&1 &
CHEM_BASE=http://127.0.0.1:3081 \
CHEM_TOKEN=$(grep -o 'token=[^ ]*' /tmp/chemver.log | cut -d= -f2) \
node dsh-ui/tests/verify-ui.cjs
```

> 지금 쓰고 있는 포트에서 실험하지 말 것 —— 별도 인스턴스를 띄우고, 끝나면 닫는다.

## 설계 원칙

1. **네트워크 제로**: 모든 계산이 이 프로세스 안에서 끝난다.
2. **추가 의존성 제로**: 코어가 쓰는 것은 RDKit뿐이고, 테스트는 pytest조차 필요 없다.
3. **실패는 사람의 말로**: RDKit의 영어 C++ 로그를 단계가 있는 진단으로 번역한다.
4. **데이터를 조용히 버리지 않는다**: 일괄 API는 한 행씩 보고한다.
5. **수치에는 항상 기준을 붙인다**: logP는 Crippen 추정값이라고 밝히고, `mw` / `exact_mw`는 각각의 의미를 설명한다.
6. **파일로 쓰고 경로를 돌려준다**: 그림을 프로토콜 페이로드에 밀어 넣지 않고 파일로 쓴 뒤 경로를 반환한다 —— 재현되고, 버전 관리에 들어가고, 논문에 쓸 수 있다.
7. **없는 것은 없다고 말한다**: 실험값은 없고, 활성 예측은 없고, 역합성 백엔드가 없으면 없다고 말한다.

## 로드맵

- **v0.1(현재)**: 완전 로컬 도구 13개 + 화학 워크벤치(캔버스 / 분석 / 역합성 프레임워크)
- **v0.2**: 역합성 백엔드가 실제로 동작(Retro* 데이터 준비) + 워크벤치에서 경로 그림을 바로 보기
- **v0.3**: 분석 카드 추가(pKa / 형태 / 약동학 성질), 시각화를 "구조 + 차트"로 격상
- **미정**: 이미지 → 구조 인식(OCSR)은 수백 MB 모델이 필요해 **"기본 경량 도구"에 속하지 않는다**. 교체 가능한 백엔드로 제공한다

## 한계

- 여기에는 실험값이 **없다**. `logP`, `TPSA`, `QED`는 모두 계산/추정값이며 실측을 대신하지 않는다.
- 구조 경고는 "독성"**이 아니다**: "이런 부분 구조는 사람이 한 번 볼 만하다"는 표시일 뿐이다.
- 여기에는 이미지 인식이 **없고**, 이름 → 구조(OPSIN 같은 것)도 **없다**.
- SMARTS 매칭은 구조 매칭이며, 화학 반응성 판단**이 아니다**.
- **생체 고분자는 표준 모노머까지만**: `peptide3`가 아는 것은 20가지 표준 아미노산의 3문자 코드뿐이다.
  수식 잔기, 비천연 모노머, 당사슬 등은 RDKit 계층에서 신뢰할 만한 지원이 없다. 또한 실측 결과 RDKit 2023.09.6의
  HELM 파싱은 **`DNA1`과 `CHEM1`을 지원하지 않는다**(None을 반환한다). 그런 경우 빈 결과를 주지 않고
  분명하게 오류를 낸다.
- **서열 타입은 반드시 당신이 지정한다**: `A/T/G/C`는 펩타이드와 핵산 양쪽에서 합법이라, 맨 서열이 모호하면
  **파싱을 거부**하고 기본값을 주지 않는다(위의 "생체 고분자" 절 참고).
- **InChI는 `*` 더미 원자를 지원하지 않는다**: 폴리머 RU-SMILES(예: `*OCCOC(=O)c1ccc(C(=O)O*)cc1`)는
  InChI / InChIKey로 **변환할 수 없다**.
  이 도구는 **조용히 빈 문자열을 돌려주지 않는다**(RDKit은 그렇게 한다). 분명하게 오류를 내고 고유 식별자로는
  canonical SMILES를 쓰라고 권한다 —— 이 분야에서 가장 흔한 입력이 바로 `*`가 붙은 것이기 때문이다.
- 이것은 **0.x 초기 릴리스**이다: API가 바뀔 수 있고, 이슈는 환영한다.

## 저장소 구조

```
src/chemcore/          순수 RDKit 코어(단일 진실 공급원) + JSON CLI 입구
src/dsh_mol_mcp/       stdio MCP 어댑터(도구 13개)
dsh-ui/                화학 워크벤치(DSH 클라이언트 플러그인: 호스트 쪽 + 브라우저 쪽)
dsh-ui/retro/          역합성 백엔드 브리지(교체 가능, 기본은 Retro*)
dsh-bundle/            DSH 번들(설정만 제공하며 위의 MCP 서버를 가리킨다)
dsh/                   수동으로 덧씌우는 patch(로컬 경로를 직접 박아 넣음)
tests/                 의존성 제로 테스트 + MCP 프로토콜 스모크 + Playwright 화면 인수
docs/                  데모 이미지와 심화 문서
```

## 환경 요구 사항(실제로 밟은 함정)

**MCP Python SDK는 반드시 1.x여야 한다**:

```bash
pip install 'mcp>=1.0,<2'
```

SDK **2.x는 `FastMCP`를 `MCPServer`로 이름을 바꿨고** API에 파괴적 변경이 있다.
이 프로젝트의 `[mcp]` extra는 이미 `<2`로 고정돼 있다. 2.x를 손으로 설치했다면 `dsh-mol-mcp`가
**무엇을 해야 하는지 분명히 알려준다**(트레이스백을 던지는 대신) —— 이 함정은 CI가 깨끗한 환경에서
실측해 찾아낸 것이지 추측이 아니다.

## 감사의 말

- [RDKit](https://www.rdkit.org/) —— 화학 코어 전체
- [Ketcher](https://github.com/epam/ketcher) —— 캔버스(로컬 wasm 렌더링, 네트워크 없음)
- [Retro*](https://github.com/binghong-ml/retro_star)(ICML 2020) —— 역합성 백엔드 중 하나

## 라이선스

MIT

<!-- dsh-mol:test-count 71 -->
<!-- dsh-mol:tool-count 13 -->
<!-- dsh-mol:ui-assertions 33 -->
