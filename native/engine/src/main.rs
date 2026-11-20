//! arboris-engine: fit a model from a CSV in one small native process.
//!
//!   arboris-engine ols   --csv FILE --y wage --x a,b [--cov hc1|hc0|classical] [--threads N]
//!   arboris-engine iv    --csv FILE --y y --x w --endog d --instruments z1,z2
//!   arboris-engine panel --csv FILE --y y --x x1,x2 --entity unit --time year
//!
//! Prints one JSON object. Any row with a missing selected cell is dropped; anything else it
//! cannot read or identify is an error with exit code 2, never a guessed result.
use arboris_engine::{csv, models};

use std::collections::HashMap;
use std::time::Instant;

fn float(value: f64) -> String {
    if value.is_finite() { format!("{value:?}") } else { "null".into() }
}

fn array(values: &[f64]) -> String {
    format!("[{}]", values.iter().map(|v| float(*v)).collect::<Vec<_>>().join(","))
}

fn quoted(text: &str) -> String {
    let mut out = String::from("\"");
    for c in text.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn split(text: Option<&String>) -> Vec<String> {
    text.map(|value| value.split(',').filter(|item| !item.is_empty()).map(str::to_string).collect()).unwrap_or_default()
}

fn run() -> Result<String, String> {
    let started = Instant::now();
    let mut args = std::env::args().skip(1);
    let model = args.next().ok_or("usage: arboris-engine ols|iv|panel --csv FILE --y NAME --x A,B")?;
    let mut options: HashMap<String, String> = HashMap::new();
    while let Some(flag) = args.next() {
        let name = flag.strip_prefix("--").ok_or_else(|| format!("unexpected argument {flag}"))?.to_string();
        options.insert(name, args.next().ok_or_else(|| format!("{flag} needs a value"))?);
    }
    let path = options.get("csv").ok_or("--csv is required")?;
    let y_name = options.get("y").ok_or("--y is required")?.clone();
    let x_names = split(options.get("x"));
    let endog = split(options.get("endog"));
    let instruments = split(options.get("instruments"));
    let threads = match options.get("threads") {
        Some(value) => value.parse().map_err(|_| "--threads must be a number")?,
        None => std::thread::available_parallelism().map(|n| n.get().min(8)).unwrap_or(1),
    };
    let mut wanted = vec![y_name.clone()];
    wanted.extend(x_names.iter().cloned());
    wanted.extend(endog.iter().cloned());
    wanted.extend(instruments.iter().cloned());
    let (entity, time) = (options.get("entity").cloned(), options.get("time").cloned());
    if model == "panel" {
        wanted.push(entity.clone().ok_or("--entity is required")?);
        wanted.push(time.clone().ok_or("--time is required")?);
    }
    let bytes = std::fs::read(path).map_err(|error| format!("cannot read {path}: {error}"))?;
    let read_started = Instant::now();
    let table = csv::read(&bytes, &wanted, threads)?;
    drop(bytes);
    let read_seconds = read_started.elapsed().as_secs_f64();
    let rows = table.columns[0].len();
    let keep: Vec<bool> = (0..rows).map(|i| table.columns.iter().all(|column| column[i].is_finite())).collect();
    let dropped = keep.iter().filter(|item| !**item).count();
    let columns: Vec<Vec<f64>> = if dropped == 0 {
        table.columns
    } else {
        table.columns.into_iter().map(|column| column.into_iter().zip(&keep).filter(|(_, k)| **k).map(|(v, _)| v).collect()).collect()
    };
    let _ = &table.names;
    let at = |name: &str| columns[wanted.iter().position(|item| item == name).expect("requested column")].as_slice();
    let (y, x): (&[f64], Vec<&[f64]>) = (at(&y_name), x_names.iter().map(|name| at(name)).collect());
    let fit_started = Instant::now();
    let fit = match model.as_str() {
        "ols" => {
            let hc = match options.get("cov").map(String::as_str).unwrap_or("hc1") {
                "classical" => None, "hc0" => Some(0), "hc1" => Some(1),
                other => return Err(format!("unknown --cov {other}")),
            };
            models::ols(y, &x, &x_names, hc, threads)?
        }
        "iv" => {
            let e: Vec<&[f64]> = endog.iter().map(|name| at(name)).collect();
            let z: Vec<&[f64]> = instruments.iter().map(|name| at(name)).collect();
            let mut names = x_names.clone();
            names.extend(endog.iter().cloned());
            models::iv_2sls(y, &x, &e, &z, &names, threads)?
        }
        "panel" => models::two_way_fe(y, &x, at(entity.as_deref().unwrap()), at(time.as_deref().unwrap()), &x_names)?,
        other => return Err(format!("unknown model {other}")),
    };
    let fit_seconds = fit_started.elapsed().as_secs_f64();
    Ok(format!(
        concat!("{{\"schema_version\":\"arboris-engine.fit/v1\",\"model\":{},\"nobs\":{},\"rows_dropped\":{},\"covariance\":{},",
                "\"distribution\":{},\"df_model\":{},\"df_resid\":{},\"r_squared\":{},\"r_squared_adj\":{},\"terms\":[{}],",
                "\"estimate\":{},\"std_error\":{},\"statistic\":{},\"p_value\":{},\"ci_lower\":{},\"ci_upper\":{},",
                "\"timing_seconds\":{{\"read\":{},\"fit\":{},\"total\":{}}}}}"),
        quoted(&model), fit.nobs, dropped, quoted(fit.covariance), quoted(fit.distribution), float(fit.df_model), float(fit.df_resid),
        float(fit.r_squared), float(fit.r_squared_adj),
        fit.terms.iter().map(|t| quoted(t)).collect::<Vec<_>>().join(","),
        array(&fit.estimate), array(&fit.std_error), array(&fit.statistic), array(&fit.p_value), array(&fit.ci_lower), array(&fit.ci_upper),
        float(read_seconds), float(fit_seconds), float(started.elapsed().as_secs_f64())))
}

fn main() {
    match run() {
        Ok(output) => println!("{output}"),
        Err(error) => { eprintln!("{{\"error\":{}}}", quoted(&error)); std::process::exit(2); }
    }
}
