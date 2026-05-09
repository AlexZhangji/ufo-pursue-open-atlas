F = 0.8, only the most recent 25 or so data points contribute to the final result, since all older data points are essentially weighted out of the solution.

*Image: A line graph titled "Data Weight (F^{n-1})" on the vertical axis versus "Data Index (older ->)" on the horizontal axis. The vertical axis ranges from 0.0 to 1.0. The horizontal axis ranges from 0 to 300. Multiple curves originate at (0, 1.0) and decay toward zero as the index increases. Each curve is labeled with an F value: F = 1 (equally weighted, a horizontal line at 1.0), F = 0.999, F = 0.998, F = 0.995, F = 0.99, F = 0.98, F = 0.95, F = 0.9, and F = 0.8. The curve for F = 0.8 decays the fastest, dropping below 0.1 before index 50.*

### Figure 35. Exponential Weights for Fading-Memory Filters

For the exponentially-weighted fading-memory filter, it can be shown that the recursive filter factor used in Eq. (12) is

$$ a_n = \frac{1 - F}{1 - F^n} $$ **(20)**

Since 0 ≤ F ≤ 1, $a_n$ in Eq. (20) does not approach zero as n approaches infinity (as the other two filters do), but instead approaches the value (1 – F). If F = 0, then $a_n$ = 1 for all n, the filter has no memory at all, and the filtered value always equals the last measurement. In the limit as F approaches one, L’Hospital’s rule can be applied to

9/10/96 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 93 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; RTI