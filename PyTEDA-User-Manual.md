# PyTEDA — Data Assimilation Benchmarking Interface

<p align="center">
  <img src="static/aml-cs.png" width="800"/>
</p>

---

# User Manual

---

# 1. Overview

The **PyTEDA Benchmarking Interface** is a web-based platform for configuring, executing, and comparing ensemble-based data assimilation methods in real time.

The interface is built on top of the **PyTEDA Python library**, which provides the scientific implementations of the assimilation algorithms, dynamical models, and benchmarking engine.

PyTEDA Web provides:

• Interactive experiment configuration
• Side-by-side comparison of assimilation methods
• Real-time error visualization
• Quantitative performance metrics
• Exportable results for research and publication

The system is designed for:

• Scientific benchmarking
• Algorithm comparison
• Educational demonstrations
• Research reproducibility
• Method development and validation

---

# 2. Software Architecture

PyTEDA Web follows a layered architecture:

```
+------------------------------------------------+
|              PyTEDA Web Interface              |
|                                                |
|  • Experiment configuration                    |
|  • Method selection                           |
|  • Visualization and charts                   |
|  • Benchmark orchestration                    |
|  • Result export                              |
+--------------------+---------------------------+
                     |
                     v
+------------------------------------------------+
|              PyTEDA Python Library             |
|                                                |
|  • EnKF, LETKF, ETKF implementations          |
|  • Dynamical models (Lorenz96)                |
|  • Assimilation engine                        |
|  • Localization and inflation                 |
|  • Metrics computation                        |
+--------------------+---------------------------+
                     |
                     v
+------------------------------------------------+
|                 TEDA Framework                 |
|                                                |
|  • Educational DA abstractions                |
|  • Model definitions                          |
|  • Experiment structure                       |
+------------------------------------------------+
```

Important:

The web interface does **not implement algorithms**.
All scientific computation is performed by the PyTEDA Python library.

---

# 3. Interface Overview

The interface contains five main sections:

1. Navigation Bar
2. Benchmark Configuration
3. Method Selection
4. Benchmark Execution
5. Results and Visualization

---

# 4. Navigation Bar

Located at the top of the interface.

| Item                  | Description            |
| --------------------- | ---------------------- |
| Author Website        | Opens academic webpage |
| AML-CS Website        | Research group         |
| Educational Resources | Tutorials              |
| How to Reference      | Citation instructions  |
| Help                  | Method descriptions    |

---

# 5. Benchmark Configuration

This section defines the global experiment parameters.

---

## 5.1 Model Selection

Currently supported:

Lorenz-96 dynamical system

Default configuration:

State dimension: n = 40
Forcing parameter: F = 8

Lorenz-96 is a standard benchmark model in data assimilation research.

---

## 5.2 Global Experiment Parameters

These parameters apply to all selected methods.

---

### Ensemble Size

Number of ensemble members.

Typical values:

Educational use: 10–20
Research use: 20–100

Effect:

Higher ensemble size improves accuracy but increases computational cost.

---

### Number of Observations (m)

Number of observed state variables per assimilation cycle.

Typical values:

Sparse observations: 5–15
Moderate: 20–30
Full observation: n

Effect:

More observations improve accuracy.

---

### Observation Noise (std_obs)

Standard deviation of observation error.

Typical values:

0.01 → low noise
0.1 → moderate noise
0.5 → high noise

Effect:

Higher noise reduces estimation accuracy.

---

### Inflation Factor (inf_fact)

Multiplicative covariance inflation factor.

Typical values:

1.00 → no inflation
1.01–1.10 → recommended

Effect:

Prevents ensemble collapse.

---

### Observation Frequency (obs_freq)

Time interval between assimilation steps.

Lower values:

More frequent assimilation
Higher accuracy
Higher cost

---

### End Time (end_time)

Total simulation duration.

Higher values allow long-term stability analysis.

---

# 6. Method Selection

Methods are selected using chips.

Each chip creates a new method instance.

Example:

Click LETKF twice → creates:

LETKF r=1
LETKF r=2

This allows parameter comparison.

Each instance is independently executed.

---

# 7. Method Instance Controls

Each method instance provides:

Remove → deletes instance
Parameter controls → modify parameters
Reorder arrows → change display order

Each instance is an independent experiment.

---

# 8. Supported Methods

---

## EnKF

Ensemble Kalman Filter.

Stochastic formulation.

Baseline reference method.

Reference:

Evensen (2009)

---

## EnKF-B-Loc

EnKF with localization.

Improves performance with small ensembles.

---

## EnKF-Cholesky

Efficient covariance inversion using Cholesky decomposition.

---

## EnKF-Modified-Cholesky

Uses precision matrix estimation.

Reference:

Niño-Ruiz et al. (2018)

---

## EnKF-Shrinkage-Precision

Uses shrinkage covariance estimation.

Reference:

Niño-Ruiz & Sandu (2015)

---

## EnKF-Naive

Computationally efficient EnKF.

---

## EnSRF

Deterministic square root filter.

---

## ETKF

Ensemble Transform Kalman Filter.

---

## LEnKF

Localized EnKF.

---

## LETKF

Localized Ensemble Transform Kalman Filter.

Recommended for large systems.

Reference:

Hunt et al. (2007)

---

# 9. Running a Benchmark

Step-by-step:

Step 1
Select model

Step 2
Configure parameters

Step 3
Select methods

Step 4
Adjust method parameters

Step 5
Click:

Run Benchmark

Execution begins immediately.

---

# 10. Execution Flow

When running benchmark:

1. Web interface creates experiment configuration
2. PyTEDA library initializes model
3. Assimilation methods are instantiated
4. Assimilation cycles executed
5. Metrics computed
6. Results streamed to interface

---

# 11. Results Visualization

After execution, results appear automatically.

---

## Error Evolution Chart

Displays RMSE over time.

Lower curve indicates better performance.

Options:

Linear scale
Log scale

---

## RMSE Radar Chart

Displays background and analysis RMSE.

Used for overall comparison.

---

## RMSE Improvement Chart

Displays percent improvement.

Higher percentage is better.

---

## Metrics Table

Displays quantitative results.

Columns:

Method
Status
Analysis RMSE
Background RMSE
Final RMSE
Mean RMSE
Minimum RMSE
Runtime
Parameters

---

# 12. Exporting Results

Click:

Download CSV

CSV contains:

Time series errors
Method parameters
Metrics

Useful for:

Python
MATLAB
Excel
Publication figures

---

# 13. Status Indicators

Green check → completed
Loading → running
Error → failed

---

# 14. Typical Workflows

---

## Workflow 1 — Compare Methods

Add:

EnKF
LETKF
ETKF

Run benchmark.

Compare RMSE.

---

## Workflow 2 — Parameter Sensitivity

Add:

LETKF r=1
LETKF r=2
LETKF r=4

Compare results.

---

## Workflow 3 — Ensemble Size Study

Run with:

N=10
N=20
N=40

Compare performance.

---

# 15. Best Practices

Recommended settings:

Ensemble size: 20–40
Inflation: 1.02–1.05
Use localization for small ensembles
Use LETKF for large systems

---

# 16. Troubleshooting

If benchmark fails:

Refresh page
Check parameters
Reduce ensemble size

---

# 17. Scientific Validity

All algorithms are implemented in the PyTEDA Python library.

Ensures:

Reproducibility
Scientific correctness
Consistency with published work

---

# 18. Intended Use

Research benchmarking
Education
Algorithm development
Teaching

---

# 19. Citation

If using PyTEDA Web or PyTEDA library, cite:

Niño-Ruiz, Elías D. (2025).
TEDA: A lightweight Python framework for educational data assimilation.
SoftwareX, 31, 102297.
[https://doi.org/10.1016/j.softx.2025.102297](https://doi.org/10.1016/j.softx.2025.102297)

Niño-Ruiz, Elías D., & Racedo Valbuena, Sebastian. (2022).
TEDA: A Computational Toolbox for Teaching Ensemble-Based Data Assimilation.
ICCS 2022, Springer.
[https://doi.org/10.1007/978-3-031-08760-8_60](https://doi.org/10.1007/978-3-031-08760-8_60)

---
