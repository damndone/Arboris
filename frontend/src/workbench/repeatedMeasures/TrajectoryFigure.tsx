import type { TrajectoryFigureContext } from "./repeatedMeasuresViewModel";

export { type TrajectoryFigureContext } from "./repeatedMeasuresViewModel";

export function TrajectoryFigure(props: { context: TrajectoryFigureContext }) {
  return (
    <figure>
      <figcaption>组别轨迹</figcaption>
      <table aria-label="组别轨迹数据表">
        <thead>
          <tr>
            <th scope="col">组别</th>
            <th scope="col">时间</th>
            <th scope="col">观测均值</th>
            <th scope="col">模型边际均值</th>
          </tr>
        </thead>
        <tbody>
          {props.context.groups.flatMap((group) => props.context.time.map((time, index) => (
            <tr key={`${group.label}:${time}`}>
              <td>{group.label}</td>
              <td>{time}</td>
              <td>{group.observed_mean[index]}</td>
              <td>{group.fitted_mean[index]}</td>
            </tr>
          )))}
        </tbody>
      </table>
    </figure>
  );
}
