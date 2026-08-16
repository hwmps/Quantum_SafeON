# Sensor Placement QUBO: Mathematical Formulation and Validation

## Overview

This document describes the mathematical formulation used to model risk-aware sensor placement as a **Quadratic Unconstrained Binary Optimization (QUBO)** problem in SentinelPath.

The formulation was originally developed and documented during the collaborative **Quantum Reframing Challenge 2026** project and has been adapted here as an English technical note for the current SentinelPath repository.

> **Scope Note**
>
> This document describes the fuller experimental QUBO formulation.
> The current interactive SentinelPath web demo uses a lighter objective for faster and more interpretable execution.

---

## 1. Problem Motivation

Safety-sensor placement can be formulated as a **combinatorial optimization problem**: given a limited sensor budget and a set of candidate installation locations, determine which sensors should be deployed to observe high-risk areas as effectively as possible.

A purely local or greedy selection strategy may struggle to represent interactions among multiple objectives and constraints, including:

- risk-weighted coverage,
- sensor installation cost,
- redundant observation between sensors,
- a fixed sensor budget, and
- mandatory coverage of high-priority zones.

SentinelPath therefore represents each sensor-installation decision as a binary variable and reformulates the placement problem as a **Quadratic Unconstrained Binary Optimization (QUBO)** problem.

The purpose of this formulation is not to claim quantum computational advantage at the current problem scale. Instead, it provides a structured path from a real-world allocation problem to a binary quadratic objective that can be:

1. solved exactly for small instances,
2. compared against classical heuristics, and
3. mapped to an Ising Hamiltonian for QAOA-based evaluation.

The resulting workflow is:

**Safety Problem → Binary Optimization → QUBO → Ising Hamiltonian → QAOA**

---

## 2. Sets and Decision Variables

### 2.1 Sets

Let:

- $J$ denote the set of candidate sensor-installation locations.
- $Z$ denote the set of modeled risk zones.
- $Z_{\mathrm{req}} \subseteq Z$ denote the subset of zones requiring explicit observation coverage.
- $C_z \subseteq J$ denote the set of sensor candidates capable of providing valid coverage for zone $z$.

For a problem with $n = |J|$ candidate locations, each candidate corresponds to one binary decision variable.

### 2.2 Binary Decision Variable

For each candidate location $j \in J$:

```math
x_j =
\begin{cases}
1, & \text{if a sensor is installed at candidate } j, \\
0, & \text{otherwise.}
\end{cases}
```

with:

```math
x_j \in \{0,1\}
```

A complete sensor-placement configuration is represented by:

```math
x = (x_1, x_2, \ldots, x_n)
```

For example, in a 12-candidate instance:

```text
110100101010
```

represents one complete sensor-placement configuration.

This binary representation makes the placement problem directly compatible with QUBO.

---

## 3. Input Parameters

### 3.1 Zone Risk Weight

For each zone $z \in Z$, let:

```math
r_z
```

denote the modeled risk weight of that zone.

Higher values of $r_z$ increase the optimization reward associated with observing the zone.

### 3.2 Sensor-to-Zone Coverage

For sensor candidate $j$ and zone $z$:

```math
a_{zj} \in [0,1]
```

denotes the fraction of zone $z$ covered by sensor $j$.

Using $A_j$ to denote the modeled coverage footprint of sensor $j$ and $Z_z$ to denote the spatial region associated with zone $z$:

```math
a_{zj}
=
\frac{
\operatorname{Area}(A_j \cap Z_z)
}{
\operatorname{Area}(Z_z)
}
```

Interpretation:

- $a_{zj}=0$: sensor $j$ does not observe zone $z$.
- $a_{zj}=1$: sensor $j$ covers the entire modeled zone.
- Intermediate values represent partial coverage.

### 3.3 Normalized Installation Cost

Let $c_j$ denote the installation cost associated with candidate $j$.

The normalized cost is:

```math
\bar{c}_j
=
\frac{c_j}{c_{\max}}
```

where:

```math
c_{\max}
=
\max_{j \in J} c_j
```

Normalization keeps the cost term on a comparable numerical scale when combined with other QUBO components.

### 3.4 Sensor Budget

Let $K$ denote the target number of selected sensors.

The intended constraint is:

```math
\sum_{j \in J} x_j = K
```

### 3.5 Objective and Penalty Weights

The fuller experimental formulation uses:

- $w_{\mathrm{cost}}$ — installation-cost weight,
- $\eta$ — redundant-coverage penalty weight,
- $\lambda_K$ — sensor-count penalty,
- $\lambda_H$ — required-zone coverage penalty.

These parameters control trade-offs among observation quality, cost, redundancy, and constraint satisfaction.

They are treated as **experimental configuration parameters rather than universal constants**.

---

## 4. Risk-Weighted Coverage Reward

The first objective component rewards sensor configurations that observe high-risk zones.

For sensor candidate $j$, define:

```math
R_j
=
\sum_{z \in Z}
r_z a_{zj}
```

A sensor covering a larger fraction of a higher-risk zone therefore receives a larger reward.

The linear coverage objective can be written as:

```math
H_{\mathrm{coverage,linear}}
=
-\sum_{j \in J}
R_j x_j
```

Equivalently:

```math
H_{\mathrm{coverage,linear}}
=
-\sum_{z \in Z}
r_z
\sum_{j \in J}
a_{zj}x_j
```

The negative sign converts coverage maximization into energy minimization.

In QUBO-coefficient form, the linear contribution can be interpreted as:

```math
Q_{jj}
\leftarrow
Q_{jj} - R_j
```

However, simple additive coverage may overvalue configurations in which multiple sensors observe the same region.

A quadratic redundant-coverage penalty is therefore added separately.

---

## 5. Installation Cost

The fuller experimental formulation also accounts for relative sensor-installation cost.

The cost term is:

```math
H_{\mathrm{cost}}
=
w_{\mathrm{cost}}
\sum_{j \in J}
\bar{c}_j x_j
```

The corresponding diagonal coefficient update is:

```math
Q_{jj}
\leftarrow
Q_{jj}
+
w_{\mathrm{cost}}\bar{c}_j
```

Increasing $w_{\mathrm{cost}}$ places greater emphasis on deployment cost, while decreasing it prioritizes observation performance more strongly.

This provides a mechanism for studying the trade-off between sensing performance and deployment cost.

> **Interactive-demo scope:**  
> The current public SentinelPath demo intentionally omits this term from its lighter QUBO objective to keep interactive execution fast and interpretable.

---

## 6. Redundant-Coverage Penalty

Two individually useful sensors do not necessarily provide twice the useful coverage.

If their sensing regions strongly overlap, part of their combined observation is redundant.

### 6.1 Geometric Overlap

Let:

```math
o_{zjk}
```

denote the modeled overlap between sensor candidates $j$ and $k$ within zone $z$.

A risk-weighted pairwise overlap score can be defined as:

```math
O_{jk}
=
\sum_{z \in Z}
r_z o_{zjk}
```

The corresponding quadratic penalty is:

```math
H_{\mathrm{overlap}}
=
\eta
\sum_{j\lt k}
O_{jk}x_jx_k
```

In coefficient form:

```math
Q_{jk}
\leftarrow
Q_{jk}
+
\eta O_{jk}
\qquad
(j\lt k)
```

This increases the energy of configurations selecting strongly overlapping sensor pairs.

### 6.2 Coverage-Product Surrogate

When exact geometric intersections are not used, pairwise overlap can be approximated using:

```math
\widetilde{o}_{zjk}
=
a_{zj}a_{zk}
```

This gives the quadratic coverage surrogate:

```math
H_{\mathrm{coverage}}
=
-\sum_{z \in Z}
r_z
\sum_j
a_{zj}x_j
+
\rho
\sum_{z \in Z}
r_z
\sum_{j\lt k}
a_{zj}a_{zk}x_jx_k
```

The first term rewards coverage of high-risk zones.

The second discourages strongly overlapping observations.

The use of exact geometric overlap or a proxy approximation is treated as an explicit modeling choice rather than as an exact physical representation of sensor behavior.

---

## 7. Sensor-Budget Constraint

Suppose exactly $K$ sensors must be selected.

The desired condition is:

```math
\sum_{j \in J}x_j = K
```

Because QUBO is unconstrained, this requirement is introduced through a quadratic penalty:

```math
H_K
=
\lambda_K
\left(
\sum_{j \in J}x_j-K
\right)^2
```

Expanding:

```math
H_K
=
\lambda_K
\left[
\left(
\sum_jx_j
\right)^2
-
2K\sum_jx_j
+
K^2
\right]
```

For binary variables:

```math
x_j^2=x_j
```

Therefore:

```math
\left(
\sum_jx_j
\right)^2
=
\sum_jx_j
+
2\sum_{j\lt k}x_jx_k
```

and:

```math
H_K
=
\lambda_K
\left[
(1-2K)\sum_jx_j
+
2\sum_{j\lt k}x_jx_k
+
K^2
\right]
```

The linear coefficient update is:

```math
Q_{jj}
\leftarrow
Q_{jj}
+
\lambda_K(1-2K)
```

The pairwise update is:

```math
Q_{jk}
\leftarrow
Q_{jk}
+
2\lambda_K
\qquad
(j\lt k)
```

The constant offset is:

```math
\mathrm{offset}
\leftarrow
\mathrm{offset}
+
\lambda_K K^2
```

The offset does not change which binary configuration minimizes the objective, but it may be retained when reproducing absolute energy values.

### Penalty Calibration

For the 12-variable experiment:

```math
2^{12}=4096
```

binary configurations can be exhaustively evaluated.

This allows the penalty strength to be checked against the intended condition:

```math
\sum_jx_j=K
```

A low QUBO energy alone is not considered sufficient if the configuration violates the intended hard constraints.

---

## 8. Required-Zone Coverage Constraint

Some zones may require explicit observation regardless of their contribution to the aggregate objective.

For each:

```math
z \in Z_{\mathrm{req}}
```

the intended condition is:

```math
\sum_{j \in C_z}x_j \ge 1
```

At least one valid sensor candidate must therefore be selected for every required zone.

### 8.1 Exact Encoding with Auxiliary Variables

A general inequality can be converted into an equality by introducing auxiliary binary variables.

Conceptually:

```math
\sum_{j \in C_z}x_j
-
1
-
s_z
=
0
```

An exact penalty can then be written as:

```math
H_{\mathrm{req},z}^{\mathrm{exact}}
=
\lambda_H
\left(
\sum_{j \in C_z}x_j
-
1
-
s_z
\right)^2
```

This can encode the constraint exactly but increases the number of binary variables required.

### 8.2 Quadratic Experimental Approximation

For a required zone covered by one valid candidate $i$:

```math
H_z
=
\lambda_H(1-x_i)
```

For two valid candidates $i$ and $j$:

```math
H_z
=
\lambda_H
(1-x_i)(1-x_j)
```

This penalty becomes zero whenever at least one valid sensor is selected.

With three or more candidates, the exact logical product introduces higher-order interactions.

Because the solver pipeline expects a quadratic model, the experimental implementation uses a quadratic approximation or truncation and records this approximation explicitly.

Recommended solutions are subsequently checked against the original required-zone constraint.

---

## 9. Full QUBO Objective

The fuller experimental sensor-placement objective combines:

1. risk-weighted observation,
2. redundant-coverage penalties,
3. installation cost,
4. the sensor-budget constraint, and
5. required-zone coverage penalties.

Conceptually:

```math
H_{\mathrm{sensor}}
=
H_{\mathrm{coverage}}
+
H_{\mathrm{cost}}
+
H_K
+
H_{\mathrm{required}}
```

Using the pairwise-overlap representation:

```math
H_{\mathrm{sensor}}(x)
=
-\sum_j R_jx_j
+
w_{\mathrm{cost}}
\sum_j\bar{c}_jx_j
+
\eta
\sum_{j\lt k}
O_{jk}x_jx_k
+
\lambda_K
\left(
\sum_jx_j-K
\right)^2
+
H_{\mathrm{required}}
```

The standard upper-triangular QUBO form is:

```math
H(x)
=
\sum_iQ_{ii}x_i
+
\sum_{i\lt j}Q_{ij}x_ix_j
+
\mathrm{offset}
```

### Interactive Demo Objective

The current public web application uses a lighter objective:

```math
H_{\mathrm{demo}}(x)
=
-\sum_z
r_z
\sum_i
a_{zi}x_i
+
\rho
\sum_z
r_z
\sum_{i\lt j}
a_{zi}a_{zj}x_ix_j
+
\lambda_K
\left(
\sum_ix_i-K
\right)^2
```

This version focuses on:

- risk-weighted coverage,
- redundant-coverage control, and
- the sensor-count constraint.

The difference between the fuller experimental formulation and the interactive demo is an explicit scope decision.

The public application is not presented as a complete industrial optimization model.

---

## 10. QUBO Matrix Convention

SentinelPath uses an **upper-triangular polynomial convention**:

```math
H(x)
=
\sum_iQ_{ii}x_i
+
\sum_{i\lt j}Q_{ij}x_ix_j
+
\mathrm{offset}
```

Each pairwise coefficient therefore appears once.

If the same objective is represented using a symmetric matrix:

```math
x^{\mathsf{T}}Qx
```

an off-diagonal polynomial coefficient $q_{ij}$ must be distributed across both symmetric entries:

```math
Q_{ij}
=
Q_{ji}
=
\frac{q_{ij}}{2}
```

This prevents pairwise terms from being counted twice.

Maintaining a consistent coefficient convention is important across:

- exact enumeration,
- heuristic solvers,
- QUBO-to-Ising conversion, and
- QAOA evaluation.

---

## 11. QUBO-to-Ising Transformation

Each binary variable is mapped to a spin variable using:

```math
x_i
=
\frac{1-z_i}{2}
```

At the operator level:

```math
x_i
\longrightarrow
\frac{I-Z_i}{2}
```

where $Z_i$ is the Pauli-$Z$ operator acting on qubit $i$.

A quadratic interaction:

```math
x_ix_j
```

becomes:

```math
\frac{1}{4}
\left(
I-Z_i-Z_j+Z_iZ_j
\right)
```

After collecting constant, linear, and pairwise terms, the cost Hamiltonian can be written as:

```math
H_C
=
\sum_i h_iZ_i
+
\sum_{i\lt j}J_{ij}Z_iZ_j
+
C
```

The constant $C$ does not affect the identity of the minimizing state.

Linear terms generate single-qubit phase contributions, while pairwise QUBO interactions generate $ZZ$-type couplings.

For a dense 12-variable QUBO, the maximum number of pairwise interactions is:

```math
\binom{12}{2}
=
66
```

The number and topology of these pairwise couplings are important contributors to circuit complexity.

---

## 12. QAOA Execution

After constructing the Ising cost Hamiltonian, SentinelPath evaluates QAOA as an additional combinatorial optimization framework.

The initial state is:

```math
|+\rangle^{\otimes n}
```

The standard mixer Hamiltonian is:

```math
H_M
=
\sum_iX_i
```

For depth $p$, the parameterized QAOA state is:

```math
|\psi(\boldsymbol{\gamma},\boldsymbol{\beta})\rangle
=
\prod_{l=1}^{p}
e^{-i\beta_lH_M}
e^{-i\gamma_lH_C}
|+\rangle^{\otimes n}
```

The classical outer-loop optimizer searches for:

```math
(
\boldsymbol{\gamma}^{*},
\boldsymbol{\beta}^{*}
)
```

that minimize:

```math
\left\langle
\psi(\boldsymbol{\gamma},\boldsymbol{\beta})
\middle|
H_C
\middle|
\psi(\boldsymbol{\gamma},\boldsymbol{\beta})
\right\rangle
```

The optimized state can be written as:

```math
|\psi\rangle
=
\sum_x
\alpha_x|x\rangle
```

with probability:

```math
P(x)
=
|\alpha_x|^2
```

The current public SentinelPath implementation uses ideal-statevector simulation to inspect the resulting probability distribution.

High-probability computational-basis states are translated into physical sensor-placement decisions.

The interpretation pipeline is:

**QAOA Statevector → Probability → Bitstring → Selected Sensors → Floor-Plan Visualization**

This allows optimization results to be inspected as engineering decisions rather than only as abstract quantum states.

> **Physical QPU status:**  
> The current repository does **not** claim execution on a physical QPU.

---

## 13. Classical Validation

Quantum results are not treated as self-validating.

Whenever the problem size permits, SentinelPath uses **exact classical optimization as the reference baseline**.

For 12 binary sensor variables:

```math
2^{12}=4096
```

states can be evaluated exhaustively.

When:

```math
K=6
```

the number of feasible six-sensor configurations is:

```math
\binom{12}{6}=924
```

The validation workflow includes:

| Method | Role |
|---|---|
| Exact Exhaustive Search | Reference optimum |
| Greedy Search | Classical heuristic |
| Simulated Annealing | Classical heuristic |
| Random Search | Control baseline |
| Ideal-Statevector QAOA | Quantum optimization experiment |

The exact solution provides a reference for determining whether heuristic or QAOA-based approaches recover the optimum on these small instances.

Hard-constraint violations are also evaluated independently of raw QUBO energy.

A state is not recommended simply because it has low energy if it violates configured constraints.

This project therefore uses QAOA as an experimental optimization framework rather than as evidence of computational quantum advantage.

---

## 14. Evaluation Metrics

The system is evaluated at multiple levels rather than through a single objective value.

### 14.1 Sensor-Placement Metrics

Relevant metrics include:

- risk-weighted coverage,
- nonlinear union coverage,
- installation cost,
- number of selected sensors,
- redundant observation, and
- required-zone constraint satisfaction.

The QUBO objective is a quadratic optimization surrogate.

After optimization, a selected configuration can additionally be evaluated using nonlinear union coverage.

For zone $z$:

```math
c_z(x)
=
1-
\prod_i
\left(
1-a_{zi}x_i
\right)
```

Overall risk-weighted union coverage is:

```math
C_{\mathrm{true}}(x)
=
\frac{
\sum_z r_zc_z(x)
}{
\sum_z r_z
}
```

This distinction is intentional:

> **QUBO provides a tractable quadratic optimization surrogate, while the selected configuration is evaluated afterward using a nonlinear union-coverage metric.**

### 14.2 Optimization Metrics

Optimization performance can be evaluated using:

- objective energy,
- exact-optimum recovery,
- optimal-state probability,
- feasible-state probability,
- approximation quality, and
- constraint-violation rate.

### 14.3 Quantum-Circuit Metrics

Quantum experiments may additionally record:

- logical qubit count,
- QAOA depth $p$,
- transpiled circuit depth,
- number of pairwise $ZZ$ or $RZZ$ interactions,
- two-qubit gate count,
- routing overhead, and
- simulator or target-backend configuration.

These are treated as implementation and resource metrics rather than evidence of quantum advantage.

---

## 15. Assumptions and Limitations

SentinelPath is a **research and portfolio prototype**, not a production emergency-management system.

Important limitations include:

- the public visualization uses a CubiCasa5K residential floor plan rather than a validated industrial BIM or CAD model,
- hazard inputs are simulated or manually configured rather than derived from live physical sensors,
- sensor coverage uses simplified two-dimensional geometry,
- pairwise overlap may use a coverage-product surrogate,
- required-zone constraints may use quadratic approximation to avoid additional binary variables,
- hazard propagation uses simplified assumptions,
- wind adjustment is not a CFD simulation,
- wall shielding is not fully modeled,
- HVAC behavior is not modeled,
- ceiling height and local turbulence are not modeled,
- evacuation uses a simplified graph or grid representation,
- congestion uses a first-order shared-corridor interaction model, and
- the current optimization instances remain small enough for exact classical verification.

Automatic floor-plan structure recognition with machine learning was discussed during the original project but was not implemented.

The experiments therefore demonstrate an optimization architecture and validation methodology rather than a calibrated digital twin of a real industrial facility.

Most importantly:

- **No quantum advantage is claimed.**
- **No physical-QPU execution is claimed.**

The value of the current work lies in the explicit problem reformulation, sequential optimization architecture, interpretable output mapping, and reproducible comparison against exact classical solutions.

---

## 16. Reproducibility

Reproducibility is treated as part of the optimization workflow.

Relevant experimental configuration information can include:

```text
overlap_mode
lambda_k
qaoa_depth
sensor_budget
hazard_configuration
weather_configuration
solver_method
```

Where appropriate, results are checked against:

- exact exhaustive enumeration,
- stored experimental outputs,
- hard-constraint validation,
- classical heuristic baselines, and
- independently computed evaluation metrics.

The repository distinguishes between:

- assumptions and measured values,
- implemented features and future work,
- simulator results and physical-QPU execution,
- quadratic optimization surrogates and post-optimization evaluation metrics, and
- collaborative contributions and independent post-competition extensions.

Failed experimental cases are retained when they are important for understanding method limitations.

For example, QAOA configurations that do not recover the exact optimum remain part of the reported experimental record.

This documentation philosophy is intended to make the project easier to inspect, reproduce, and critique.

---

## Provenance

SentinelPath originated from a collaborative team project developed for the **Quantum Reframing Challenge 2026**.

The original project included collaborative work on:

- problem formulation,
- optimization architecture,
- QUBO/QAOA methodology,
- scenario modeling,
- experimental design, and
- validation.

I authored the original Korean technical note documenting the sensor-placement QUBO formulation during that project.

This document reorganizes and expands that material in English for the current SentinelPath portfolio repository while preserving the collaborative origin of the underlying project.

Following the competition, I independently extended the prototype into a more complete software and technical-demonstration system, including:

- interactive end-to-end workflow design,
- QAOA computational-basis state extraction,
- QAOA state-distribution visualization,
- bitstring-to-sensor interpretation,
- state-to-floor-plan highlighting,
- exact-optimum comparison logic,
- interface restructuring,
- reproducibility improvements,
- English-language technical documentation, and
- AWS Elastic Beanstalk deployment.

The post-competition work should therefore be understood as an independent engineering extension of the original collaborative research prototype rather than as a separate reimplementation of the team's work.

### Original Technical Note

The original Korean QUBO formulation is preserved in the team repository:

**[Quantum Reframing QUBO Mathematical Formulation — Original Korean Technical Note](https://github.com/walkerprocess/Quantum_SafeON/issues/1)**

### Scope and Claim Boundaries

This documentation intentionally distinguishes:

**Original collaborative research**  
→ problem formulation, optimization methodology, experimental framework, and scenario design

from:

**Independent post-competition engineering**  
→ interpretability features, application development, deployment, documentation, and portfolio-oriented system extensions.

This distinction is maintained to preserve project history, attribution, and reproducibility.
