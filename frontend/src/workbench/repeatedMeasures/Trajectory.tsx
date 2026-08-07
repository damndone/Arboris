import { parseCanonicalTrajectory } from "./repeatedMeasuresViewModel";

export function Trajectory({ context }: { context: unknown }) {
  const trajectory = parseCanonicalTrajectory(context);
  if (trajectory === null) return null;
  return (
    <section aria-label="lmm-group-trajectory">
      <h3>Group trajectories</h3>
      <table>
        <thead>
          <tr><th>Group</th><th>Time</th><th>Observed mean</th><th>Fitted mean</th></tr>
        </thead>
        <tbody>
          {trajectory.groups.flatMap((group) => trajectory.time.map((time, index) => (
            <tr key={`${group.label}-${time}`}>
              <td>{group.label}</td><td>{time}</td>
              <td>{group.observed_mean[index]}</td><td>{group.fitted_mean[index]}</td>
            </tr>
          )))}
        </tbody>
      </table>
    </section>
  );
}
