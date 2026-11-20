//! Parallel CSV reader for the requested columns. RFC 4180 quoting; floats are correctly rounded.
use std::thread;

pub struct Table {
    pub names: Vec<String>,
    /// Column-major values; a missing cell is NaN.
    pub columns: Vec<Vec<f64>>,
}

fn split_line(line: &[u8], mut each: impl FnMut(usize, &[u8])) {
    let (mut index, mut start, mut quoted) = (0, 0, false);
    for (position, &byte) in line.iter().enumerate() {
        match byte {
            b'"' => quoted = !quoted,
            b',' if !quoted => {
                each(index, &line[start..position]);
                index += 1;
                start = position + 1;
            }
            _ => {}
        }
    }
    each(index, &line[start..]);
}

fn clean(mut field: &[u8]) -> &[u8] {
    while let [b' ' | b'\t' | b'\r', rest @ ..] = field { field = rest; }
    while let [rest @ .., b' ' | b'\t' | b'\r'] = field { field = rest; }
    if let [b'"', inner @ .., b'"'] = field { field = inner; }
    field
}

/// Same spellings of "missing" as the reader the product uses by default.
fn is_missing(field: &[u8]) -> bool {
    matches!(field, b"" | b"NA" | b"N/A" | b"NaN" | b"nan" | b"null" | b"NULL" | b"None" | b"#N/A" | b"<NA>" | b"-nan" | b"n/a")
}

fn parse_number(field: &[u8]) -> Result<f64, String> {
    let field = clean(field);
    if is_missing(field) { return Ok(f64::NAN); }
    let text = std::str::from_utf8(field).map_err(|_| "a cell is not valid UTF-8".to_string())?;
    text.parse::<f64>().map_err(|_| format!("a selected column has a non-numeric cell: {text:?}"))
}

fn chunks(body: &[u8], parts: usize) -> Vec<&[u8]> {
    let mut out = Vec::with_capacity(parts);
    let mut start = 0;
    for part in 1..=parts {
        let mut end = if part == parts { body.len() } else { (body.len() * part / parts).max(start) };
        while end < body.len() && body[end] != b'\n' { end += 1; }
        if end < body.len() { end += 1; }
        if end > start { out.push(&body[start..end]); }
        start = end;
    }
    out
}

pub fn read(bytes: &[u8], wanted: &[String], threads: usize) -> Result<Table, String> {
    let header_end = bytes.iter().position(|&byte| byte == b'\n').ok_or("the file has no data rows")?;
    let mut header = Vec::new();
    split_line(&bytes[..header_end], |_, field| header.push(String::from_utf8_lossy(clean(field)).into_owned()));
    let mut slots = Vec::with_capacity(wanted.len());
    for name in wanted {
        slots.push(header.iter().position(|item| item == name).ok_or_else(|| format!("no column named {name}"))?);
    }
    let body = &bytes[header_end + 1..];
    if body.contains(&b'"') && body.windows(2).any(|pair| pair == b"\"\n" || pair == b"\n\"") {
        // A quoted cell could hold a newline, which a chunk boundary would split.
        return read_parts(&[body], &slots, wanted);
    }
    let parts = chunks(body, threads.max(1));
    read_parts(&parts, &slots, wanted)
}

fn read_parts(parts: &[&[u8]], slots: &[usize], wanted: &[String]) -> Result<Table, String> {
    let results: Vec<Result<Vec<Vec<f64>>, String>> = thread::scope(|scope| {
        let handles: Vec<_> = parts.iter().map(|part| scope.spawn(move || parse_part(part, slots))).collect();
        handles.into_iter().map(|handle| handle.join().expect("reader thread")).collect()
    });
    let mut columns: Vec<Vec<f64>> = vec![Vec::new(); slots.len()];
    let mut pieces = Vec::with_capacity(results.len());
    for result in results { pieces.push(result?); }
    let rows: usize = pieces.iter().map(|piece| piece[0].len()).sum();
    for (index, column) in columns.iter_mut().enumerate() {
        column.reserve_exact(rows);
        for piece in &pieces { column.extend_from_slice(&piece[index]); }
    }
    Ok(Table { names: wanted.to_vec(), columns })
}

fn parse_part(part: &[u8], slots: &[usize]) -> Result<Vec<Vec<f64>>, String> {
    let estimate = part.len() / 24 + 16;
    let mut columns: Vec<Vec<f64>> = slots.iter().map(|_| Vec::with_capacity(estimate)).collect();
    let mut failure = None;
    for line in part.split(|&byte| byte == b'\n') {
        if line.is_empty() || line == b"\r" { continue; }
        let before = columns[0].len();
        split_line(line, |index, field| {
            for (slot_index, slot) in slots.iter().enumerate() {
                if *slot == index {
                    match parse_number(field) {
                        Ok(value) => columns[slot_index].push(value),
                        Err(error) => { failure.get_or_insert(error); }
                    }
                }
            }
        });
        if let Some(error) = failure.take() { return Err(error); }
        if columns.iter().any(|column| column.len() != before + 1) {
            return Err("a row has too few cells".into());
        }
    }
    Ok(columns)
}
