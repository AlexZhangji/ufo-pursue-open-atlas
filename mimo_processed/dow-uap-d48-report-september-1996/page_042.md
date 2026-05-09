cumulative angle turned versus time. Since the slope of the curve (i.e., the turning rate) is greatest when the thrust (and thus airframe) is directed at right angles to the velocity vector, the average angular acceleration during the first 90° of rotation was obtained from the equation

$$ \theta = \frac{1}{2} \ddot{\theta} t^2 \qquad (4) $$

so that

$$ \ddot{\theta} = \frac{2 \theta \text{ (deg)}}{t^2 \text{ (sec}^2)} = \frac{180 \text{ deg}}{t^2 \text{ sec}^2} \qquad (5) $$

where *t* is the elapsed time from the beginning of the tumble turn until the airframe has rotated approximately 90°. If the assumption is made that the angular acceleration is directly proportional to the thrust offset angle (i.e., nozzle deflection), the angular acceleration $\ddot{\theta}_d$ for any small deflection angle becomes

$$ \ddot{\theta}_d = \ddot{\theta} \frac{\delta_d}{\delta} \qquad (6) $$

where $\ddot{\theta}$ is the angular acceleration computed from Eq. (5) for deflection angle $\delta$ (1° for Atlas IIAS), and $\delta_d$ is some small deflection angle.

Using the Atlas IIAS data, angular accelerations $\ddot{\theta}$ were computed at ten-second intervals from the programming time of 15 seconds to 275 seconds for $\delta$ = 1°. For each starting time, a normal distribution with zero mean and a standard deviation of 0.1° was sampled to obtain an initial thrust misalignment $\delta_d$ to substitute in Eq. (6). The resulting angular acceleration $\ddot{\theta}_d$ was applied throughout the turn. Slow-turn calculations were made in a manner analogous to the random-attitude turns, using the reference trajectory to obtain the starting position and velocity components. The slow turn was assumed to occur in a randomly oriented plane containing the starting velocity vector. Each turn was carried out until one of the four conditions listed in Section 6.1.1 for random-attitude turns was met. For conditions (1) and (4), impact points were calculated and, along with thrusting impacts from condition (2), summed for each five-degree sector from 0° to 175°. At each starting time, 10,000 impact-point calculations were made.

### 6.1.3 Factors Affecting Malfunction-Turn Results

Random-attitude turns and slow turns are only subsets of the totality of Mode-5 failure responses. As discussed earlier in Section 3, other types of behavior following a Mode-5 failure are numerous and largely impossible to categorize, much less simulate. Ideally, impact distributions from all types of Mode-5 responses should be combined before results are compared with those obtained from the theoretical Mode-5 impact

---
9/10/96 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 33 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; RTI