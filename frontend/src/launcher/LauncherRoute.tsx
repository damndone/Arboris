// v1.6.8 route inversion — `/` is the Launcher, not the Submit form.
// This is the T9 skeleton: heading + create-project affordance. T10 fills in
// the recent-projects grid (localStorage) and the create-project modal.

export function LauncherRoute() {
  return (
    <section className="panel" aria-labelledby="launcher-heading">
      <div className="panel-heading">
        <h2 id="launcher-heading">Econometrics Workbench</h2>
        <span>选择或新建一个项目开始。</span>
      </div>
      <button type="button">新建项目</button>
      <p className="muted">最近项目将显示在这里。</p>
    </section>
  );
}
