#!/usr/bin/env python3
"""
CSV Import Script untuk Supabase
File: data/import_csv_to_supabase.py

Usage: python data/import_csv_to_supabase.py
"""

import pandas as pd
import os
from supabase import create_client, Client
from datetime import datetime
from dotenv import load_dotenv

# Indonesian month mapping
INDONESIAN_MONTHS = {
    'Januari': 'January', 'Februari': 'February', 'Maret': 'March',
    'April': 'April', 'Mei': 'May', 'Juni': 'June',
    'Juli': 'July', 'Agustus': 'August', 'September': 'September',
    'Oktober': 'October', 'November': 'November', 'Desember': 'December'
}

def convert_indonesian_date(date_str: str) -> str:
    """Convert Indonesian month names to English"""
    for indo_month, eng_month in INDONESIAN_MONTHS.items():
        if indo_month in date_str:
            return date_str.replace(indo_month, eng_month)
    return date_str

# Load environment variables
load_dotenv()

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def get_supabase_client() -> Client:
    """Initialize Supabase client"""
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def import_jadwal_kuliah(supabase: Client):
    """Import jadwal_kuliah.csv to Supabase"""
    print("Importing jadwal_kuliah.csv...")
    
    try:
        df = pd.read_csv('data/csv_files/jadwal_kuliah.csv')
        
        # Convert data to list of dictionaries
        data_list = []
        for _, row in df.iterrows():
            # Handle date conversion
            berlaku_mulai = None
            if pd.notna(row['berlaku_mulai']):
                try:
                    berlaku_mulai = datetime.strptime(str(row['berlaku_mulai']), '%d %b %Y').date().isoformat()
                except:
                    berlaku_mulai = None
            
            data_list.append({
                'input_kelas': row['input_kelas'].strip().lower(),
                'kelas': row['kelas'],
                'hari': row['hari'],
                'mata_kuliah': row['mata_kuliah'],
                'waktu': row['waktu'] if pd.notna(row['waktu']) else None,
                'ruang': row['ruang'] if pd.notna(row['ruang']) else None,
                'dosen': row['dosen'] if pd.notna(row['dosen']) else None,
                'berlaku_mulai': berlaku_mulai
            })
        
        # Insert data
        result = supabase.table('jadwal_kuliah').insert(data_list).execute()
        print(f"✓ Imported {len(data_list)} rows to jadwal_kuliah")
        
    except Exception as e:
        print(f"✗ Error importing jadwal_kuliah: {str(e)}")

def import_jadwal_uas(supabase: Client):
    """Import jadwal_uas.csv to Supabase"""
    print("Importing jadwal_uas.csv...")
    
    try:
        df = pd.read_csv('data/csv_files/jadwal_uas.csv')
        print(f"Debug: Found {len(df)} rows in CSV")
        
        data_list = []
        skipped_rows = 0
        
        for index, row in df.iterrows():
            # Convert date dengan Indonesian month support
            tanggal = None
            if pd.notna(row['tanggal']) and str(row['tanggal']).strip():
                tanggal_str = str(row['tanggal']).strip()
                
                # Convert Indonesian month names to English
                tanggal_eng = convert_indonesian_date(tanggal_str)
                print(f"Row {index}: '{tanggal_str}' -> '{tanggal_eng}'")
                
                # Try different date formats
                date_formats = [
                    '%d %B %Y',      # 01 August 2025 (after conversion)
                    '%d %b %Y',      # 01 Aug 2025
                    '%Y-%m-%d',      # 2025-08-01
                    '%d/%m/%Y',      # 01/08/2025
                    '%d-%m-%Y',      # 01-08-2025
                ]
                
                for fmt in date_formats:
                    try:
                        tanggal = datetime.strptime(tanggal_eng, fmt).date().isoformat()
                        print(f"✓ Parsed successfully: {tanggal}")
                        break
                    except ValueError as e:
                        continue
                
                if not tanggal:
                    print(f"✗ Could not parse date '{tanggal_str}' -> '{tanggal_eng}' at row {index}")
                    skipped_rows += 1
                    continue
            else:
                print(f"✗ Empty/null date at row {index}")
                skipped_rows += 1
                continue
            
            data_list.append({
                'kelas': row['kelas'],
                'hari': row['hari'],
                'tanggal': tanggal,
                'mata_kuliah': row['mata_kuliah'],
                'waktu': row['waktu']
            })
        
        if data_list:
            result = supabase.table('jadwal_uas').insert(data_list).execute()
            print(f"✓ Imported {len(data_list)} rows to jadwal_uas")
            if skipped_rows > 0:
                print(f"⚠ Skipped {skipped_rows} rows due to invalid dates")
        else:
            print("✗ No valid rows to import")
        
    except Exception as e:
        print(f"✗ Error importing jadwal_uas: {str(e)}")
        # Print more debug info
        print("Debug: Sample of CSV data:")
        try:
            df = pd.read_csv('data/csv_files/jadwal_uas.csv')
            print(df.head(3))
            print(f"Columns: {df.columns.tolist()}")
        except:
            pass

def import_wali_kelas(supabase: Client):
    """Import wali_kelas.csv to Supabase"""
    print("Importing wali_kelas.csv...")
    
    try:
        df = pd.read_csv('data/csv_files/wali_kelas.csv')
        
        data_list = []
        for _, row in df.iterrows():
            data_list.append({
                'prefix': row['prefix'],
                'kelas': row['kelas'],
                'dosen': row['dosen']
            })
        
        result = supabase.table('wali_kelas').insert(data_list).execute()
        print(f"✓ Imported {len(data_list)} rows to wali_kelas")
        
    except Exception as e:
        print(f"✗ Error importing wali_kelas: {str(e)}")

def import_jadwal_loket(supabase: Client):
    """Import loket.csv to Supabase"""
    print("Importing loket.csv...")
    
    try:
        df = pd.read_csv('data/csv_files/loket.csv')
        
        data_list = []
        for _, row in df.iterrows():
            data_list.append({
                'section': row['section'],
                'hari': row['hari'],
                'jenis': row['jenis'],
                'waktu_raw': row['waktu_raw'],
                'start_time': row['start_time'],
                'end_time': row['end_time']
            })
        
        result = supabase.table('jadwal_loket').insert(data_list).execute()
        print(f"✓ Imported {len(data_list)} rows to jadwal_loket")
        
    except Exception as e:
        print(f"✗ Error importing jadwal_loket: {str(e)}")

def clear_all_tables(supabase: Client):
    """Clear all tables (optional - untuk re-import)"""
    print("Clearing all tables...")
    
    try:
        tables = ['jadwal_kuliah', 'jadwal_uas', 'wali_kelas', 'jadwal_loket']
        for table in tables:
            supabase.table(table).delete().neq('id', 0).execute()
            print(f"✓ Cleared table: {table}")
    except Exception as e:
        print(f"✗ Error clearing tables: {str(e)}")

def import_kalender_akademik(supabase: Client):
    """Import kalender_akademik.csv ke Supabase (header: title,order,level,kegiatan,parent_kegiatan,tanggal_raw,start_date,end_date)"""
    print("Importing kalender_akademik.csv...")
    try:
        import pandas as pd
        from datetime import datetime

        path = 'data/csv_files/kalender_akademik.csv'
        df = pd.read_csv(path)

        # Normalisasi kolom 'order' -> 'ord'
        if 'order' in df.columns and 'ord' not in df.columns:
            df = df.rename(columns={'order': 'ord'})

        rows = []
        for _, r in df.iterrows():
            def _coerce_date(x):
                if pd.isna(x) or str(x).strip() == '':
                    return None
                s = str(x).strip()
                # sudah ISO? biarkan
                try:
                    return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
                except Exception:
                    # fallback lain kalau perlu
                    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y"):
                        try:
                            return datetime.strptime(s, fmt).date().isoformat()
                        except Exception:
                            pass
                return None

            rows.append({
                'title': r.get('title'),
                'ord': int(r.get('ord')) if pd.notna(r.get('ord')) else 0,
                'level': int(r.get('level')) if pd.notna(r.get('level')) else 1,
                'kegiatan': r.get('kegiatan'),
                'parent_kegiatan': r.get('parent_kegiatan') if pd.notna(r.get('parent_kegiatan')) else None,
                'tanggal_raw': r.get('tanggal_raw') if pd.notna(r.get('tanggal_raw')) else None,
                'start_date': _coerce_date(r.get('start_date')),
                'end_date': _coerce_date(r.get('end_date')),
            })

        if rows:
            supabase.table('kalender_akademik').insert(rows).execute()
            print(f"✓ Imported {len(rows)} rows to kalender_akademik")
        else:
            print("✗ No valid rows to import for kalender_akademik")

    except Exception as e:
        print(f"✗ Error importing kalender_akademik: {e}")

def main():
    """Main import function"""
    print("Starting CSV import to Supabase...")
    print(f"Supabase URL: {SUPABASE_URL}")
    
    # Initialize client
    supabase = get_supabase_client()
    
    # Ask user if they want to clear tables first
    clear_tables = input("Clear existing data? (y/N): ").lower() == 'y'
    if clear_tables:
        clear_all_tables(supabase)
    
    print("\n" + "="*50)
    print("IMPORTING CSV DATA TO SUPABASE")
    print("="*50)
    
    # Import all CSV files
    import_jadwal_kuliah(supabase)
    import_jadwal_uas(supabase)
    import_wali_kelas(supabase)
    import_jadwal_loket(supabase)
    import_kalender_akademik(supabase)
    
    print("\n" + "="*50)
    print("IMPORT COMPLETED!")
    print("="*50)

if __name__ == "__main__":
    main()