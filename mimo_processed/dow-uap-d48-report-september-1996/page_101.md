For the recursive form of this filter, where each datum is weighted by its position in the chronological sequence, the recursive filter factor for the n<sup>th</sup> point is given by

$$ a_n = \frac{n}{\sum_{i=1}^n i} = \frac{2n}{n(n+1)} = \frac{2}{n+1} $$ (16)

Using Eq. (12),

| | | |
| :--- | :--- | :--- |
| n = 1 | a<sub>1</sub> = 1 | <span style="text-decoration: overline">X</span><sub>1</sub> = x<sub>1</sub> = 6 |
| n = 2 | a<sub>2</sub> = 2/3 | <span style="text-decoration: overline">X</span><sub>2</sub> = 6 + 2/3(5–6) = 5.33 |
| n = 3 | a<sub>3</sub> = 1/2 | <span style="text-decoration: overline">X</span><sub>3</sub> = 5.33 + 1/2(7–5.33) = 6.17 |

(17)

The “memory” (i.e., importance) of older data in this filter fades at a rate dictated by the filter. In this case, the 50<sup>th</sup> value is 50 times more important than the first, and the 100<sup>th</sup> value is twice as important as the 50<sup>th</sup> and 100 times more important than the first.

The exponentially-weighted filter provides the analyst with more flexibility. This filter uses F<sup>i</sup> as a weighting factor, where the filter-control constant F is a value chosen between zero and one, and i is the “age-count” of the i<sup>th</sup> data point. For this filter, i = 0 now designates the current or latest data point, i = 1 designates the immediately preceding or next-to-last data point, etc., so the data points are indexed in reverse chronological order starting with zero. The weighted least-squares solution is

$$ \bar{X}_n = \frac{\sum_{i=0}^{n-1} F^i x_{n-i}}{\sum_{i=0}^{n-1} F^i} $$ (18)

Using F = 0.9 and the same example as before,

$$ \bar{X}_3 = \frac{F^0x_3 + F^1x_2 + F^2x_1}{F^0 + F^1 + F^2} $$

$$ = \frac{(.9)^0(7) + (.9)^1(5) + (.9)^2(6)}{(.9)^0 + (.9)^1 + (.9)^2} $$ (19)

$$ = \frac{7 + 4.5 + 4.86}{2.71} = \frac{16.36}{2.71} = 6.04 $$

The weighting of each data point for sample sizes up to 300 is shown in Figure 35 for values of F from 0.8 to 1.0. For F = 1, all points in the sample are weighted equally. For

9/10/96
92
RTI