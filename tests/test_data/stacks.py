"""The stacks the platform can onboard — WHAT a codebase is built from.

A stack is the platform's own pipeline selector. The portal resolves a build run as
`<gitProvider>-<buildTool>-<framework>-<type[:3]>-build-<versioning>`, so buildTool,
framework and codebase type together decide which pipeline runs, while the strategy
and versioning scheme are separate axes (see codebase_data's builders).

`lang` is NOT part of that name: it reaches the Codebase CR and the create-strategy
template repo, but never the pipeline. Two stacks can therefore share one pipeline —
c and cpp both resolve to `cmake-none-app` — which is why the catalog is keyed by a
name that includes the language.

The catalog mirrors the portal's own language -> frameworks x buildTools mapping. The
gitops system codebase is deliberately absent: scripts/bootstrap.py owns it, and tests
never provision a platform prerequisite.
"""

from dataclasses import dataclass
from typing import Literal

CodebaseType = Literal["application", "library", "autotest", "infrastructure"]

# Longest slug that still fits a scenario tag inside unique_name's 30-char DNS-1123
# budget once the run id and an xdist worker suffix are taken; asserted in the unit tests.
MAX_SLUG = 10

_TEMPLATE_REPO_OWNER = "https://github.com/epmd-edp"


@dataclass(frozen=True)
class Stack:
    """One lang/framework/buildTool/type combination the platform offers."""

    lang: str
    framework: str
    build_tool: str
    codebase_type: CodebaseType
    # Short, stable name fragment a scenario folds into its unique_name prefix.
    slug: str
    # Workload-relative build cost. Effective build wait =
    # krci_timeout_build_success * build_timeout_factor: the run knob knows how fast
    # the CLUSTER is, the stack knows how heavy the WORKLOAD is.
    build_timeout_factor: float = 1.0

    @property
    def key(self) -> str:
        """Catalog key. Carries the language, which the pipeline name does not, so
        stacks sharing a pipeline stay distinct entries."""
        return f"{self.lang}-{self.build_tool}-{self.framework}-{self.codebase_type[:3]}"

    @property
    def pipeline_stem(self) -> str:
        """The part of a Tekton pipeline name the platform derives from this stack —
        what a cluster-capability check matches installed pipelines against."""
        return f"{self.build_tool}-{self.framework}-{self.codebase_type[:3]}"

    @property
    def deployable(self) -> bool:
        """Only applications produce an image a CD stage can deploy."""
        return self.codebase_type == "application"

    @property
    def template_repo_url(self) -> str:
        """The public scaffold the create strategy clones (<lang>-<buildTool>-<framework>).
        Clone scenarios use it as their source: no credentials, and its content matches
        this stack's pipelines. Marketplace Templates carry their own source instead."""
        return f"{_TEMPLATE_REPO_OWNER}/{self.lang}-{self.build_tool}-{self.framework}.git"


_STACKS: tuple[Stack, ...] = (
    # application
    Stack("c", "none", "cmake", "application", "noneca"),
    Stack("c", "none", "make", "application", "nonema"),
    Stack("cpp", "none", "cmake", "application", "cnoneca"),
    Stack("cpp", "none", "make", "application", "cnonema"),
    Stack("csharp", "dotnet-3.1", "dotnet", "application", "dotnet3da"),
    Stack("csharp", "dotnet-6.0", "dotnet", "application", "dotnet6da"),
    Stack("go", "beego", "go", "application", "beegoga"),
    Stack("go", "gin", "go", "application", "ginga"),
    Stack("go", "operator-sdk", "go", "application", "operatoga"),
    Stack("helm", "helm", "helm", "application", "helmha"),
    Stack("java", "java17", "gradle", "application", "java17ga"),
    Stack("java", "java21", "gradle", "application", "java21ga"),
    Stack("java", "java25", "gradle", "application", "java25ga"),
    Stack("java", "java17", "maven", "application", "java17ma"),
    Stack("java", "java21", "maven", "application", "java21ma"),
    Stack("java", "java25", "maven", "application", "java25ma"),
    Stack("javascript", "angular", "npm", "application", "angularna"),
    Stack("javascript", "antora", "npm", "application", "antorana"),
    Stack("javascript", "express", "npm", "application", "expressna"),
    Stack("javascript", "next", "npm", "application", "nextna"),
    Stack("javascript", "react", "npm", "application", "reactna"),
    Stack("javascript", "vue", "npm", "application", "vuena"),
    Stack("javascript", "angular", "pnpm", "application", "angularpa"),
    Stack("javascript", "antora", "pnpm", "application", "antorapa"),
    Stack("javascript", "express", "pnpm", "application", "expresspa"),
    Stack("javascript", "next", "pnpm", "application", "nextpa"),
    Stack("javascript", "react", "pnpm", "application", "reactpa"),
    Stack("javascript", "vue", "pnpm", "application", "vuepa"),
    Stack("python", "fastapi", "python", "application", "fastapipa"),
    Stack("python", "flask", "python", "application", "flaskpa"),
    Stack("python", "python-3.13", "python", "application", "python3pa"),
    # library
    Stack("container", "docker", "kaniko", "library", "dockerkl"),
    Stack("csharp", "dotnet-3.1", "dotnet", "library", "dotnet3dl"),
    Stack("csharp", "dotnet-6.0", "dotnet", "library", "dotnet6dl"),
    Stack("groovy-pipeline", "codenarc", "codenarc", "library", "codenarcl"),
    Stack("hcl", "terraform", "terraform", "library", "terrafotl"),
    Stack("helm", "charts", "helm", "library", "chartshl"),
    Stack("helm", "pipeline", "helm", "library", "pipelinhl", 0.5),
    Stack("java", "java17", "gradle", "library", "java17gl"),
    Stack("java", "java21", "gradle", "library", "java21gl"),
    Stack("java", "java25", "gradle", "library", "java25gl"),
    Stack("java", "java17", "maven", "library", "java17ml"),
    Stack("java", "java21", "maven", "library", "java21ml"),
    Stack("java", "java25", "maven", "library", "java25ml"),
    Stack("javascript", "angular", "npm", "library", "angularnl"),
    Stack("javascript", "express", "npm", "library", "expressnl"),
    Stack("javascript", "next", "npm", "library", "nextnl"),
    Stack("javascript", "react", "npm", "library", "reactnl"),
    Stack("javascript", "vue", "npm", "library", "vuenl"),
    Stack("javascript", "angular", "pnpm", "library", "angularpl"),
    Stack("javascript", "express", "pnpm", "library", "expresspl"),
    Stack("javascript", "next", "pnpm", "library", "nextpl"),
    Stack("javascript", "react", "pnpm", "library", "reactpl"),
    Stack("javascript", "vue", "pnpm", "library", "vuepl"),
    Stack("python", "ansible", "python", "library", "ansiblepl"),
    Stack("python", "python-3.13", "python", "library", "python3pl"),
    Stack("rego", "opa", "opa", "library", "opaol"),
    # autotest
    Stack("java", "java17", "gradle", "autotest", "java17gt"),
    Stack("java", "java21", "gradle", "autotest", "java21gt"),
    Stack("java", "java25", "gradle", "autotest", "java25gt"),
    Stack("java", "java17", "maven", "autotest", "java17mt"),
    Stack("java", "java21", "maven", "autotest", "java21mt"),
    Stack("java", "java25", "maven", "autotest", "java25mt"),
    # infrastructure
    Stack("hcl", "aws", "terraform", "infrastructure", "awsti"),
)

CATALOG: dict[str, Stack] = {stack.key: stack for stack in _STACKS}


def deployable(stacks: dict[str, Stack]) -> dict[str, Stack]:
    """Only the stacks a CD stage can deploy, so a deploy scenario cannot pick a
    library, an autotest or an infrastructure stack that produces no image."""
    return {key: stack for key, stack in stacks.items() if stack.deployable}


# The three stacks the smoke suite names directly.
HELM_LIBRARY = CATALOG["helm-helm-pipeline-lib"]
PY_FASTAPI = CATALOG["python-python-fastapi-app"]
GO_GIN = CATALOG["go-go-gin-app"]
