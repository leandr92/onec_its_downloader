//! Extract files from 1C ITS ISCF (cabinet-like) containers.
//!
//! Layout notes (empirical from V8Doc Storage/Data.cab):
//! - Signature `ISCF` instead of `MSCF`
//! - Reserve length is a single `u32` at offset 36 (not the MS three-`u16` sizes)
//! - CFFOLDER entries are standard (`coffCabStart`, `cCFData`, `typeCompress`)
//! - Compression `0x1573` = LZX window 21 (same as `0x1503` for decoding)
//! - CFDATA has no per-block reserve (`cbCFData == 0` for walking)
//! - CFFILE ring: at `coffFiles` a leading `size:u32`, `offset:u32`, `folder:u16`, then
//!   repeated `hash:u32`, `type:u16` (=0x20), `path\0`, then the next record's size/offset/folder.
//!   The leading triple belongs to the first path; the last path has no trailing triple.

use lzxd::{Lzxd, WindowSize};
use std::env;
use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

#[derive(Debug)]
struct Folder {
    data_offset: u32,
    block_count: u16,
    compression: u16,
}

#[derive(Debug, Clone)]
struct CabFile {
    path: String,
    size: u32,
    offset: u32,
    folder: u16,
}

fn read_u16(data: &[u8], off: usize) -> u16 {
    u16::from_le_bytes(data[off..off + 2].try_into().unwrap())
}

fn read_u32(data: &[u8], off: usize) -> u32 {
    u32::from_le_bytes(data[off..off + 4].try_into().unwrap())
}

fn parse_iscf(data: &[u8]) -> io::Result<(Vec<Folder>, Vec<CabFile>)> {
    if data.len() < 40 || &data[0..4] != b"ISCF" {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "not an ISCF container"));
    }
    let coff_files = read_u32(data, 16) as usize;
    let c_folders = read_u16(data, 26) as usize;
    let c_files = read_u16(data, 28) as usize;
    let reserve_len = read_u32(data, 36) as usize;
    let folder_off = 36 + 4 + reserve_len;

    let mut folders = Vec::with_capacity(c_folders);
    for i in 0..c_folders {
        let off = folder_off + i * 8;
        folders.push(Folder {
            data_offset: read_u32(data, off),
            block_count: read_u16(data, off + 4),
            compression: read_u16(data, off + 6),
        });
    }

    // File directory: size/offset/folder precede each path's hash/type/name.
    let dir_end = folders
        .first()
        .map(|f| f.data_offset as usize)
        .unwrap_or(data.len());
    let mut pos = coff_files;
    if pos + 10 > dir_end {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "empty file directory"));
    }
    let mut size = read_u32(data, pos);
    let mut offset = read_u32(data, pos + 4);
    let mut folder = read_u16(data, pos + 8);
    pos += 10;
    let mut files = Vec::with_capacity(c_files);
    while files.len() < c_files && pos + 6 < dir_end {
        let typ = read_u16(data, pos + 4);
        let name_start = pos + 6;
        let name_end = match data[name_start..dir_end].iter().position(|&b| b == 0) {
            Some(n) => name_start + n,
            None => break,
        };
        let path = decode_cp1251(&data[name_start..name_end]);
        pos = name_end + 1;
        if typ == 0x20 && (folder as usize) < folders.len() {
            files.push(CabFile {
                path,
                size,
                offset,
                folder,
            });
        }
        if files.len() >= c_files || pos + 10 > dir_end {
            break;
        }
        size = read_u32(data, pos);
        offset = read_u32(data, pos + 4);
        folder = read_u16(data, pos + 8);
        pos += 10;
    }

    Ok((folders, files))
}

fn decode_cp1251(bytes: &[u8]) -> String {
    bytes
        .iter()
        .map(|&b| {
            if b < 0x80 {
                b as char
            } else {
                // Minimal CP1251 mapping for Cyrillic used in ITS paths.
                CP1251[b as usize - 0x80]
            }
        })
        .collect()
}

/// CP1251 codepoints for 0x80..0xFF.
const CP1251: [char; 128] = [
    '\u{0402}', '\u{0403}', '\u{201A}', '\u{0453}', '\u{201E}', '\u{2026}', '\u{2020}', '\u{2021}',
    '\u{20AC}', '\u{2030}', '\u{0409}', '\u{2039}', '\u{040A}', '\u{040C}', '\u{040B}', '\u{040F}',
    '\u{0452}', '\u{2018}', '\u{2019}', '\u{201C}', '\u{201D}', '\u{2022}', '\u{2013}', '\u{2014}',
    '\u{FFFD}', '\u{2122}', '\u{0459}', '\u{203A}', '\u{045A}', '\u{045C}', '\u{045B}', '\u{045F}',
    '\u{00A0}', '\u{040E}', '\u{045E}', '\u{0408}', '\u{00A4}', '\u{0490}', '\u{00A6}', '\u{00A7}',
    '\u{0401}', '\u{00A9}', '\u{0404}', '\u{00AB}', '\u{00AC}', '\u{00AD}', '\u{00AE}', '\u{0407}',
    '\u{00B0}', '\u{00B1}', '\u{0406}', '\u{0456}', '\u{0491}', '\u{00B5}', '\u{00B6}', '\u{00B7}',
    '\u{0451}', '\u{2116}', '\u{0454}', '\u{00BB}', '\u{0458}', '\u{0405}', '\u{0455}', '\u{0457}',
    '\u{0410}', '\u{0411}', '\u{0412}', '\u{0413}', '\u{0414}', '\u{0415}', '\u{0416}', '\u{0417}',
    '\u{0418}', '\u{0419}', '\u{041A}', '\u{041B}', '\u{041C}', '\u{041D}', '\u{041E}', '\u{041F}',
    '\u{0420}', '\u{0421}', '\u{0422}', '\u{0423}', '\u{0424}', '\u{0425}', '\u{0426}', '\u{0427}',
    '\u{0428}', '\u{0429}', '\u{042A}', '\u{042B}', '\u{042C}', '\u{042D}', '\u{042E}', '\u{042F}',
    '\u{0430}', '\u{0431}', '\u{0432}', '\u{0433}', '\u{0434}', '\u{0435}', '\u{0436}', '\u{0437}',
    '\u{0438}', '\u{0439}', '\u{043A}', '\u{043B}', '\u{043C}', '\u{043D}', '\u{043E}', '\u{043F}',
    '\u{0440}', '\u{0441}', '\u{0442}', '\u{0443}', '\u{0444}', '\u{0445}', '\u{0446}', '\u{0447}',
    '\u{0448}', '\u{0449}', '\u{044A}', '\u{044B}', '\u{044C}', '\u{044D}', '\u{044E}', '\u{044F}',
];

fn window_size(compression: u16) -> io::Result<WindowSize> {
    // Low nibble 3 = LZX; window in bits 8..12.
    if compression & 0xf != 3 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!("unsupported compression {compression:#x}"),
        ));
    }
    match (compression >> 8) & 0x1f {
        15 => Ok(WindowSize::KB32),
        16 => Ok(WindowSize::KB64),
        17 => Ok(WindowSize::KB128),
        18 => Ok(WindowSize::KB256),
        19 => Ok(WindowSize::KB512),
        20 => Ok(WindowSize::MB1),
        21 => Ok(WindowSize::MB2),
        22 => Ok(WindowSize::MB4),
        23 => Ok(WindowSize::MB8),
        24 => Ok(WindowSize::MB16),
        25 => Ok(WindowSize::MB32),
        w => Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!("invalid LZX window {w}"),
        )),
    }
}

/// Plain LZX streams in ITS cabs start with these four bytes (E8 header on).
const LZX_PROLOGUE: u32 = 0x8d80_805b; // file bytes 5b 80 80 8d

fn detect_payload_xor_key(data: &[u8], folders: &[Folder]) -> Option<[u8; 4]> {
    let folder = folders.first()?;
    if folder.block_count == 0 {
        return None;
    }
    let pos = folder.data_offset as usize;
    if pos + 12 > data.len() {
        return None;
    }
    let cb_data = read_u16(data, pos + 4) as usize;
    if cb_data < 4 || pos + 8 + cb_data > data.len() {
        return None;
    }
    let magic = read_u32(data, pos + 8);
    if magic == LZX_PROLOGUE {
        return None;
    }
    Some((magic ^ LZX_PROLOGUE).to_le_bytes())
}

fn xor_payload(chunk: &[u8], key: &[u8; 4]) -> Vec<u8> {
    chunk
        .iter()
        .enumerate()
        .map(|(i, b)| b ^ key[i % 4])
        .collect()
}

fn decompress_folder(
    data: &[u8],
    folder: &Folder,
    xor_key: Option<[u8; 4]>,
) -> io::Result<Vec<u8>> {
    let mut lzxd = Lzxd::new(window_size(folder.compression)?);
    let mut out = Vec::new();
    let mut pos = folder.data_offset as usize;
    for _ in 0..folder.block_count {
        if pos + 8 > data.len() {
            return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "CFDATA truncated"));
        }
        let cb_data = read_u16(data, pos + 4) as usize;
        let cb_uncomp = read_u16(data, pos + 6) as usize;
        pos += 8;
        if pos + cb_data > data.len() {
            return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "CFDATA payload truncated"));
        }
        let raw = &data[pos..pos + cb_data];
        pos += cb_data;
        let owned;
        let chunk = if let Some(key) = xor_key {
            owned = xor_payload(raw, &key);
            owned.as_slice()
        } else {
            raw
        };
        let decoded = lzxd
            .decompress_next(chunk, cb_uncomp)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, format!("LZX: {e:?}")))?;
        out.extend_from_slice(decoded);
    }
    Ok(out)
}

fn safe_join(base: &Path, rel: &str) -> io::Result<PathBuf> {
    let rel = rel.replace('\\', "/");
    let mut out = base.to_path_buf();
    for part in rel.split('/') {
        if part.is_empty() || part == "." {
            continue;
        }
        if part == ".." {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "path escapes"));
        }
        out.push(part);
    }
    Ok(out)
}

fn extract(cab_path: &Path, out_dir: &Path) -> io::Result<(usize, usize)> {
    let mut file = File::open(cab_path)?;
    let mut data = Vec::new();
    file.read_to_end(&mut data)?;
    let (folders, files) = parse_iscf(&data)?;
    let xor_key = detect_payload_xor_key(&data, &folders);

    let mut folder_data: Vec<Option<Vec<u8>>> = (0..folders.len()).map(|_| None).collect();
    let mut written = 0usize;
    for f in &files {
        let idx = f.folder as usize;
        if folder_data[idx].is_none() {
            folder_data[idx] = Some(decompress_folder(&data, &folders[idx], xor_key)?);
        }
        let blob = folder_data[idx].as_ref().unwrap();
        let start = f.offset as usize;
        let end = start + f.size as usize;
        if end > blob.len() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("file {} oob in folder {idx}", f.path),
            ));
        }
        let dest = safe_join(out_dir, &f.path)?;
        if let Some(parent) = dest.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut out = File::create(&dest)?;
        out.write_all(&blob[start..end])?;
        written += 1;
    }
    Ok((written, files.len()))
}

fn main() {
    let mut args = env::args().skip(1);
    let cab = match args.next() {
        Some(p) => PathBuf::from(p),
        None => {
            eprintln!("usage: iscf_extract <Data.cab> <out_dir>");
            std::process::exit(2);
        }
    };
    let out = match args.next() {
        Some(p) => PathBuf::from(p),
        None => {
            eprintln!("usage: iscf_extract <Data.cab> <out_dir>");
            std::process::exit(2);
        }
    };
    match extract(&cab, &out) {
        Ok((n, total)) => println!("extracted {n}/{total} files into {}", out.display()),
        Err(e) => {
            eprintln!("error: {e}");
            std::process::exit(1);
        }
    }
}
