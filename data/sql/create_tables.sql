-- SQL Schema untuk Supabase Tables
-- File: data/sql/create_tables.sql

-- Table: jadwal_kuliah
CREATE TABLE jadwal_kuliah (
    id SERIAL PRIMARY KEY,
    input_kelas VARCHAR(10) NOT NULL,
    kelas VARCHAR(10) NOT NULL,
    hari VARCHAR(20) NOT NULL,
    mata_kuliah VARCHAR(255) NOT NULL,
    waktu VARCHAR(50),
    ruang VARCHAR(100),
    dosen VARCHAR(255),
    berlaku_mulai DATE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Table: jadwal_uas
CREATE TABLE jadwal_uas (
    id SERIAL PRIMARY KEY,
    kelas VARCHAR(10) NOT NULL,
    hari VARCHAR(20) NOT NULL,
    tanggal DATE NOT NULL,
    mata_kuliah VARCHAR(255) NOT NULL,
    waktu VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Table: wali_kelas
CREATE TABLE wali_kelas (
    id SERIAL PRIMARY KEY,
    prefix VARCHAR(10) NOT NULL,
    kelas VARCHAR(10) NOT NULL,
    dosen VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Table: jadwal_loket
CREATE TABLE jadwal_loket (
    id SERIAL PRIMARY KEY,
    section VARCHAR(255) NOT NULL,
    hari VARCHAR(50) NOT NULL,
    jenis VARCHAR(50) NOT NULL,
    waktu_raw VARCHAR(100) NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Tabel Kalender Akademik
CREATE TABLE kalender_akademik (
    id serial primary key,
    title text not null,             -- "Kalender Akademik Genap (ATA) 2024/2025"
    ord int not null,                -- urutan (dari CSV: "order")
    level int not null,              -- 1/2
    kegiatan text not null,          -- deskripsi
    parent_kegiatan text default null,
    tanggal_raw text default null,   -- teks asli rentang tanggal (opsional)
    start_date date default null,
    end_date date default null,
    created_at timestamp default now(),
    updated_at timestamp default now()
);
-- Indexes untuk optimasi query
CREATE INDEX idx_jadwal_kuliah_input_kelas ON jadwal_kuliah(input_kelas);
CREATE INDEX idx_jadwal_kuliah_kelas ON jadwal_kuliah(kelas);
CREATE INDEX idx_jadwal_kuliah_dosen ON jadwal_kuliah(dosen);
CREATE INDEX idx_jadwal_uas_kelas ON jadwal_uas(kelas);
CREATE INDEX idx_wali_kelas_kelas ON wali_kelas(kelas);
CREATE INDEX idx_jadwal_loket_hari ON jadwal_loket(hari);
create index idx_kal_start on kalender_akademik (start_date);
create index idx_kal_end   on kalender_akademik (end_date);
create index idx_kal_kegiatan_ci on kalender_akademik (lower(kegiatan));

-- Enable Row Level Security (RLS) - Optional untuk production
-- ALTER TABLE jadwal_kuliah ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE jadwal_uas ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE wali_kelas ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE jadwal_loket ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE kalender_akademik ENABLE ROW LEVEL SECURITY;