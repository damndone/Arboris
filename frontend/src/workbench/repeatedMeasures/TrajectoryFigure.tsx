export type TrajectoryFigureContext = {
  title: string;
  aria_label: string;
  paths: ReadonlyArray<{
    id: string;
    label: string;
    d: string;
  }>;
};

export function TrajectoryFigure(props: { context: TrajectoryFigureContext }) {
  return (
    <figure>
      <figcaption>{props.context.title}</figcaption>
      <svg viewBox="0 0 100 100" role="img" aria-label={props.context.aria_label}>
        {props.context.paths.map((path) => (
          <path key={path.id} data-testid={`trajectory-${path.id}`} d={path.d} fill="none" />
        ))}
      </svg>
      <ul aria-label="Trajectory legend">
        {props.context.paths.map((path) => <li key={path.id}>{path.label}</li>)}
      </ul>
    </figure>
  );
}
