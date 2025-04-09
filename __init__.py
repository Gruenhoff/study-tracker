from aqt import mw
from aqt.qt import *
from anki.hooks import addHook, wrap
import sqlite3
from datetime import datetime, timedelta
from aqt.qt import QAction
import os
import csv
import json
import re
import traceback
import time
import urllib.request
import hashlib
import shutil

# Konstanten
ADDON_PATH = os.path.dirname(__file__)
DB_PATH = os.path.join(ADDON_PATH, "study_tracker.db")
BACKUP_DIR = os.path.join(ADDON_PATH, "backups")
MOBILE_SCREEN_WIDTH = 600  # Pixel für Smartphone-Erkennung
GITHUB_REPO = "Study-Tracker/anki-addon"
VERSION = "2.1.0"

# Hilfsfunktion für Qt-Enum Kompatibilität
def get_qt_enum(enum_class, enum_value):
    """
    Hilfsfunktion zum Umgang mit verschiedenen Qt-Enum-Formaten zwischen PyQt5 und PyQt6
    """
    try:
        # Versuche PyQt6-Stil (Qt.AlignmentFlag.AlignCenter)
        return getattr(enum_class, enum_value)
    except (AttributeError, TypeError):
        try:
            # Versuche PyQt5-Stil (Qt.AlignCenter)
            return getattr(Qt, enum_value)
        except AttributeError:
            print(f"Study Tracker: Konnte Qt Enum {enum_value} nicht finden, verwende Fallback.")
            return 0  # Fallback-Wert
        
# Stile für das Add-on
CSS_STYLES = """
    QFrame.cell {
        min-height: 12px;
        max-height: 12px;
        min-width: 12px;
        max-width: 12px;
        border-radius: 2px;
    }
    QFrame.cell:hover {
        border: 1px solid #000;
    }
    QLabel.level {
        font-weight: bold;
        color: #388e3c;
    }
    QProgressBar {
        border: 1px solid #E0E0E0;
        border-radius: 2px;
        text-align: center;
    }
    QProgressBar::chunk {
        background-color: #4CAF50;
    }
"""

print("Study Tracker: Initialisierung gestartet...")

# Hilfsfunktionen
def format_date(date_obj, format_string="%d.%m.%Y"):
    """Formatiert ein Datum in einen lesbaren String"""
    if isinstance(date_obj, str):
        try:
            date_obj = datetime.strptime(date_obj, "%Y-%m-%d").date()
        except ValueError:
            try:
                date_obj = datetime.strptime(date_obj, "%Y-%m-%d %H:%M:%S").date()
            except ValueError:
                return date_obj
    return date_obj.strftime(format_string)

def clean_html(html_text):
    """Entfernt HTML-Tags aus einem Text"""
    if not html_text:
        return ""
    return re.sub(r'<[^>]+>', '', html_text)

def escape_html(text):
    """Escaped HTML-Sonderzeichen"""
    if not text:
        return ""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))

def check_updates():
    """Überprüft, ob eine neue Version des Add-ons verfügbar ist"""
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        response = urllib.request.urlopen(url)
        data = json.loads(response.read())
        latest_version = data["tag_name"].strip("v")
        
        if latest_version > VERSION:
            QMessageBox.information(
                mw,
                "Study Tracker Update",
                f"Eine neue Version ({latest_version}) ist verfügbar!\n"
                f"Download: github.com/{GITHUB_REPO}/releases"
            )
    except Exception as e:
        print(f"Fehler bei Update-Prüfung: {e}")

def migrate_database(db):
    """Führt Migrationen für alte Datenbanktabellen durch"""
    try:
        print("Study Tracker: Prüfe auf notwendige Datenbankmigrationen...")
        cursor = db.conn.cursor()
        
        # Prüfe level_progress Tabelle
        cursor.execute("PRAGMA table_info(level_progress)")
        columns = {col[1]: col for col in cursor.fetchall()}
        
        # Prüfe, ob deck_id ein NOT NULL constraint hat
        if 'deck_id' in columns and columns['deck_id'][3] == 1:  # NOT NULL constraint ist vorhanden
            print("Study Tracker: Migration - Entferne NOT NULL constraint von deck_id in level_progress")
            
            # Erstelle temporäre Tabelle ohne NOT NULL constraint
            db.conn.executescript("""
                -- Backup der bestehenden Daten
                CREATE TEMPORARY TABLE level_progress_backup AS 
                SELECT * FROM level_progress;
                
                -- Löschen der alten Tabelle
                DROP TABLE level_progress;
                
                -- Erstellen der neuen Tabelle ohne NOT NULL constraint
                CREATE TABLE level_progress (
                    id INTEGER PRIMARY KEY,
                    deck_id INTEGER DEFAULT 0,
                    current_level INTEGER DEFAULT 1,
                    level_start_date TEXT,
                    last_updated TEXT
                );
                
                -- Wiederherstellen der Daten
                INSERT INTO level_progress (id, deck_id, current_level, level_start_date, last_updated)
                SELECT id, 
                       COALESCE(deck_id, 0), 
                       current_level, 
                       level_start_date, 
                       last_updated 
                FROM level_progress_backup;
                
                -- Löschen der temporären Tabelle
                DROP TABLE level_progress_backup;
                
                -- Index für schnelleren Zugriff
                CREATE INDEX IF NOT EXISTS idx_level_progress_deck 
                ON level_progress(deck_id);
            """)
            
            print("Study Tracker: Migration der level_progress Tabelle abgeschlossen")
        
        db.conn.commit()
        return True
    except Exception as e:
        print(f"Study Tracker: Fehler bei der Datenbankmigration: {e}")
        traceback.print_exc()
        return False

class Database:
    """Verbesserte Datenbankklasse mit robuster Fehlerbehandlung"""
    def __init__(self):
        self.conn = None
        self.last_error = None
        try:
            print("Study Tracker: Initialisiere Datenbankverbindung")
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            self.conn = sqlite3.connect(DB_PATH)
            self.create_tables()
            migrate_database(self)  # Führe Migrationen aus
            self.ensure_optimized_indices()  # Erstelle optimierte Indices
            print("Study Tracker: Datenbankverbindung hergestellt")
        except Exception as e:
            self.last_error = str(e)
            print(f"Study Tracker: Fehler bei Datenbankinitialisierung: {e}")
            self.handle_db_error(e)
        
    def initialize_connection(self):
        """Stellt die Verbindung zur Datenbank her und erstellt Tabellen"""
        try:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            self.conn = sqlite3.connect(DB_PATH)
            self.create_tables()
            print("Study Tracker: Datenbankverbindung hergestellt")
        except Exception as e:
            self.last_error = str(e)
            print(f"Study Tracker: Fehler bei Datenbankinitialisierung: {e}")
            self.handle_db_error(e)
    
    def create_tables(self):
        """Erstellt alle benötigten Tabellen in der Datenbank"""
        try:
            with self.conn:
                self.conn.executescript("""
                    -- Tabelle für tägliche Statistiken
                    CREATE TABLE IF NOT EXISTS daily_stats (
                        date TEXT,
                        deck_id INTEGER,
                        cards_due INTEGER DEFAULT 0,
                        cards_studied INTEGER DEFAULT 0,
                        study_time INTEGER DEFAULT 0,
                        PRIMARY KEY (date, deck_id)
                    );
                    
                    -- Tabelle für den Level-Fortschritt
                    CREATE TABLE IF NOT EXISTS level_progress (
                        id INTEGER PRIMARY KEY,
                        deck_id INTEGER DEFAULT 0, -- Defaultwert 0 statt NOT NULL-Constraint
                        current_level INTEGER DEFAULT 1,
                        level_start_date TEXT,
                        last_updated TEXT
                );
                    
                    -- Tabelle für allgemeine Einstellungen
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    );
                    
                    -- Tabelle für Validierungscodes
                    CREATE TABLE IF NOT EXISTS validation_codes (
                        id INTEGER PRIMARY KEY,
                        deck_id INTEGER,
                        card_id TEXT,
                        date TEXT,
                        code TEXT,
                        correct_percent INTEGER,
                        difficulty INTEGER,
                        page_number INTEGER,
                        chat_link TEXT,
                        card_title TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );

                    -- Tabelle für Level-Änderungshistorie
                    CREATE TABLE IF NOT EXISTS level_history (
                        id INTEGER PRIMARY KEY,
                        deck_id INTEGER,
                        change_type TEXT,
                        old_level INTEGER,
                        new_level INTEGER,
                        change_date TEXT
                    );
                    
                    -- Tabelle für Streak-Rekorde
                    CREATE TABLE IF NOT EXISTS streak_records (
                        id INTEGER PRIMARY KEY,
                        deck_id INTEGER,
                        record INTEGER NOT NULL,
                        date TEXT NOT NULL
                    );

                    -- Tabelle für Synchronisierungshistorie
                    CREATE TABLE IF NOT EXISTS sync_history (
                        id INTEGER PRIMARY KEY,
                        last_sync_date TEXT NOT NULL
                    );
                    
                    -- Tabelle für ChatGPT-Links
                    CREATE TABLE IF NOT EXISTS chat_links (
                        id INTEGER PRIMARY KEY,
                        card_id TEXT NOT NULL,
                        deck_id INTEGER,
                        link TEXT NOT NULL,
                        card_title TEXT,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (card_id)
                    );
                    
                    -- Tabelle für gelernte Karten pro Tag
                    CREATE TABLE IF NOT EXISTS studied_cards (
                        id INTEGER PRIMARY KEY,
                        date TEXT NOT NULL,
                        card_id TEXT NOT NULL,
                        deck_id INTEGER,
                        review_time INTEGER DEFAULT 0,
                        UNIQUE(date, card_id)
                    );
                    
                    -- Indizes für schnelleren Zugriff
                    CREATE INDEX IF NOT EXISTS idx_daily_stats_date 
                    ON daily_stats(date);
                    
                    CREATE INDEX IF NOT EXISTS idx_daily_stats_deck 
                    ON daily_stats(deck_id);
                    
                    CREATE INDEX IF NOT EXISTS idx_level_history_deck 
                    ON level_history(deck_id);
                    
                    CREATE INDEX IF NOT EXISTS idx_validation_codes_date 
                    ON validation_codes(date);
                    
                    CREATE INDEX IF NOT EXISTS idx_validation_codes_deck 
                    ON validation_codes(deck_id);
                    
                    CREATE INDEX IF NOT EXISTS idx_validation_codes_card 
                    ON validation_codes(card_id);
                    
                    CREATE INDEX IF NOT EXISTS idx_chat_links_card 
                    ON chat_links(card_id);
                    
                    CREATE INDEX IF NOT EXISTS idx_chat_links_deck 
                    ON chat_links(deck_id);
                    
                    CREATE INDEX IF NOT EXISTS idx_studied_cards_date 
                    ON studied_cards(date);
                    
                    CREATE INDEX IF NOT EXISTS idx_studied_cards_deck 
                    ON studied_cards(deck_id);
                    
                    CREATE INDEX IF NOT EXISTS idx_level_progress_deck 
                    ON level_progress(deck_id);
                """)

                print("Study Tracker: Datenbanktabellen erfolgreich erstellt")
        except Exception as e:
            self.last_error = str(e)
            print(f"Study Tracker: Fehler beim Erstellen der Tabellen: {e}")
            self.handle_db_error(e)
    
    def ensure_optimized_indices(self):
        """Stellt sicher, dass alle notwendigen Indices für Performance existieren"""
        try:
            with self.conn:
                self.conn.executescript("""
                    -- Optimiert für Berichte über lange Zeiträume
                    CREATE INDEX IF NOT EXISTS idx_validation_codes_deck_date 
                    ON validation_codes(deck_id, date);
                    
                    -- Optimiert für ChatGPT-Link-Lookups
                    CREATE INDEX IF NOT EXISTS idx_chat_links_compound 
                    ON chat_links(card_id, deck_id);
                    
                    -- Optimiert für Level-Historie-Abfragen
                    CREATE INDEX IF NOT EXISTS idx_level_history_deck_date 
                    ON level_history(deck_id, date(change_date));
                """)
            print("Study Tracker: Optimierte Indices erstellt")
            return True
        except Exception as e:
            print(f"Study Tracker: Fehler beim Erstellen optimierter Indices: {e}")
            self.handle_db_error(e)
            return False
    
    def repair_database_if_needed(self):
        """Prüft und repariert die Datenbank, falls nötig"""
        try:
            # Prüfe Integrität
            cursor = self.conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            
            if result != "ok":
                print(f"Study Tracker: Datenbank-Integritätsprobleme: {result}")
                
                # Erstelle Backup
                backup_path = os.path.join(BACKUP_DIR, f"corrupt_db_backup_{int(time.time())}.db")
                os.makedirs(BACKUP_DIR, exist_ok=True)
                
                with sqlite3.connect(backup_path) as backup_db:
                    self.conn.backup(backup_db)
                    
                print(f"Study Tracker: Backup der beschädigten Datenbank erstellt: {backup_path}")
                
                # Versuche Reparatur
                self.conn.execute("VACUUM")
                return False
            return True
        except Exception as e:
            print(f"Study Tracker: Fehler bei Datenbank-Integritätsprüfung: {e}")
            return False
    
    def handle_db_error(self, error):
        """Zentrale Fehlerbehandlung für Datenbankoperationen"""
        print(f"Datenbankfehler: {str(error)}")
        traceback.print_exc()
        
        # Erstelle Backup bei Datenbankfehlern
        try:
            if self.conn:
                backup_path = os.path.join(
                    BACKUP_DIR, 
                    f"study_tracker_error_backup_{int(time.time())}.db"
                )
                os.makedirs(BACKUP_DIR, exist_ok=True)
                with sqlite3.connect(backup_path) as backup_db:
                    self.conn.backup(backup_db)
                print(f"Datenbank-Backup erstellt unter: {backup_path}")
        except Exception as backup_error:
            print(f"Backup konnte nicht erstellt werden: {backup_error}")
    
    def close(self):
        """Schließt die Datenbankverbindung sicher"""
        if hasattr(self, 'conn') and self.conn:
            try:
                self.conn.commit()
                self.conn.close()
                print("Study Tracker: Datenbankverbindung geschlossen")
            except Exception as e:
                print(f"Study Tracker: Fehler beim Schließen der Datenbank: {e}")
    
    def get_setting(self, key, default=None):
        """Holt eine Einstellung aus der Datenbank"""
        try:
            cursor = self.conn.execute("""
                SELECT value FROM settings WHERE key = ?
            """, (key,))
            result = cursor.fetchone()
            return result[0] if result else default
        except Exception as e:
            print(f"Fehler beim Abrufen der Einstellung '{key}': {e}")
            return default
    
    def save_setting(self, key, value):
        """Speichert eine Einstellung in der Datenbank"""
        try:
            with self.conn:
                self.conn.execute("""
                    INSERT OR REPLACE INTO settings (key, value)
                    VALUES (?, ?)
                """, (key, value))
            return True
        except Exception as e:
            print(f"Fehler beim Speichern der Einstellung '{key}': {e}")
            self.handle_db_error(e)
            return False
    
    def save_selected_deck(self, deck_name):
        """Speichert den ausgewählten Stapel"""
        return self.save_setting('selected_deck', deck_name)
    
    def get_selected_deck(self):
        """Lädt den gespeicherten Stapel"""
        return self.get_setting('selected_deck')
    
    def update_sync_date(self):
        """Aktualisiert das letzte Synchronisierungsdatum"""
        try:
            with self.conn:
                self.conn.execute("""
                    INSERT OR REPLACE INTO sync_history (id, last_sync_date)
                    VALUES (1, ?)
                """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
            return True
        except Exception as e:
            print(f"Fehler beim Aktualisieren des Synchronisierungsdatums: {e}")
            self.handle_db_error(e)
            return False
    
    def get_last_sync_date(self):
        """Ruft das letzte Synchronisierungsdatum ab"""
        try:
            cursor = self.conn.execute("""
                SELECT last_sync_date FROM sync_history WHERE id = 1
            """)
            result = cursor.fetchone()
            if result:
                return datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
            return None
        except Exception as e:
            print(f"Fehler beim Abrufen des letzten Synchronisierungsdatums: {e}")
            return None
    
    def save_daily_stats(self, date, deck_id, cards_due, cards_studied, study_time):
        """Speichert oder aktualisiert die Tagesstatistik für ein Deck"""
        try:
            with self.conn:
                self.conn.execute("""
                    INSERT OR REPLACE INTO daily_stats 
                    (date, deck_id, cards_due, cards_studied, study_time)
                    VALUES (?, ?, ?, ?, ?)
                """, (date, deck_id, cards_due, cards_studied, study_time))
            return True
        except Exception as e:
            print(f"Fehler beim Speichern der Tagesstatistik: {e}")
            self.handle_db_error(e)
            return False
    
    def get_daily_stats(self, date, deck_id=None):
        """Holt die Tagesstatistik für ein Datum und optional ein Deck"""
        try:
            if deck_id:
                cursor = self.conn.execute("""
                    SELECT cards_due, cards_studied, study_time
                    FROM daily_stats
                    WHERE date = ? AND deck_id = ?
                """, (date, deck_id))
                result = cursor.fetchone()
                if result:
                    return {
                        'cards_due': result[0],
                        'cards_studied': result[1],
                        'study_time': result[2]
                    }
                return {'cards_due': 0, 'cards_studied': 0, 'study_time': 0}
            else:
                # Summe über alle Decks
                cursor = self.conn.execute("""
                    SELECT SUM(cards_due), SUM(cards_studied), SUM(study_time)
                    FROM daily_stats
                    WHERE date = ?
                """, (date,))
                result = cursor.fetchone()
                if result and result[0] is not None:
                    return {
                        'cards_due': result[0],
                        'cards_studied': result[1],
                        'study_time': result[2]
                    }
                return {'cards_due': 0, 'cards_studied': 0, 'study_time': 0}
        except Exception as e:
            print(f"Fehler beim Abrufen der Tagesstatistik: {e}")
            return {'cards_due': 0, 'cards_studied': 0, 'study_time': 0}
    
    def save_level_progress(self, deck_id, level, start_date):
        """Speichert den Level-Fortschritt für ein Deck"""
        try:
            # Wenn deck_id None ist, verwenden wir 0 als globale Deck-ID
            safe_deck_id = deck_id if deck_id is not None else 0
            
            with self.conn:
                self.conn.execute("""
                    INSERT OR REPLACE INTO level_progress
                    (deck_id, current_level, level_start_date, last_updated)
                    VALUES (?, ?, ?, ?)
                """, (
                    safe_deck_id,
                    level,
                    start_date.strftime("%Y-%m-%d") if isinstance(start_date, datetime) else start_date,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
            return True
        except Exception as e:
            print(f"Fehler beim Speichern des Level-Fortschritts: {e}")
            self.handle_db_error(e)
            return False
    
    def get_level_progress(self, deck_id):
        """Holt den Level-Fortschritt für ein Deck"""
        try:
            # Wenn deck_id None ist, verwenden wir 0 als globale Deck-ID
            safe_deck_id = deck_id if deck_id is not None else 0
            
            cursor = self.conn.execute("""
                SELECT current_level, level_start_date
                FROM level_progress
                WHERE deck_id = ?
            """, (safe_deck_id,))
            result = cursor.fetchone()
            if result:
                return {
                    'level': result[0],
                    'start_date': datetime.strptime(result[1], "%Y-%m-%d").date() if result[1] else datetime.now().date()
                }
            return None
        except Exception as e:
            print(f"Fehler beim Abrufen des Level-Fortschritts: {e}")
            return None
    
    def save_level_change(self, deck_id, change_type, old_level, new_level):
        """Speichert eine Level-Änderung mit verbessertem Debugging und Fehlerbehandlung"""
        try:
            print(f"Study Tracker: Speichere Level-Änderung - deck_id={deck_id}, type={change_type}, old={old_level}, new={new_level}")
            
            # Stelle sicher, dass deck_id ein Integer ist
            deck_id_int = int(deck_id) if deck_id is not None else 0
            
            # Prüfe, ob die Tabelle existiert
            cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='level_history'")
            if not cursor.fetchone():
                print("KRITISCHER FEHLER: Tabelle level_history existiert nicht!")
                # ... [existing table creation code stays the same] ...
                
            # NEU: Prüfe, ob heute bereits ein Eintrag mit dem gleichen change_type für dieses Deck existiert
            today = datetime.now().strftime("%Y-%m-%d")
            cursor = self.conn.execute("""
                SELECT COUNT(*) FROM level_history
                WHERE deck_id = ? AND change_type = ? AND change_date LIKE ?
            """, (deck_id_int, change_type, f"{today}%"))
            
            count = cursor.fetchone()[0]
            if count > 0:
                print(f"Study Tracker: Für heute existiert bereits ein '{change_type}' Eintrag für Deck {deck_id_int}. Überspringe.")
                return True  # Kein Fehler, aber keine neue Einfügung
            
            # Führe die Einfügung mit try/except durch
            try:
                insert_query = """
                    INSERT INTO level_history
                    (deck_id, change_type, old_level, new_level, change_date)
                    VALUES (?, ?, ?, ?, ?)
                """
                
                change_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.conn.execute(insert_query, (
                    deck_id_int,
                    change_type,
                    int(old_level),
                    int(new_level),
                    change_date
                ))
                self.conn.commit()  # Wichtig: Sofort committen
                
                print(f"Level-Änderung eingefügt - Abfrage: {insert_query}")
                print(f"Parameter: ({deck_id_int}, {change_type}, {old_level}, {new_level}, {change_date})")
                
                # Prüfe, ob der Eintrag gespeichert wurde
                cursor = self.conn.execute("""
                    SELECT * FROM level_history 
                    WHERE deck_id = ? AND change_type = ? AND change_date = ?
                    LIMIT 1
                """, (deck_id_int, change_type, change_date))
                
                result = cursor.fetchone()
                if result:
                    print(f"Level-Änderung erfolgreich gespeichert: {result}")
                    return True
                else:
                    print("FEHLER: Konnte den gespeicherten Eintrag nicht finden!")
                    return False
            except Exception as e:
                print(f"FEHLER beim Einfügen: {e}")
                traceback.print_exc()
                return False
                
        except Exception as e:
            print(f"Allgemeiner Fehler beim Speichern der Level-Änderung: {e}")
            traceback.print_exc()
            self.handle_db_error(e)
            return False
    
    def get_level_history(self, deck_id, start_date=None, end_date=None):
        """Holt die Level-Änderungshistorie für ein Deck mit verbesserter Fehlerbehandlung"""
        try:
            print(f"Study Tracker: Hole Level-Historie für Deck {deck_id}, Zeitraum {start_date} bis {end_date}")
            
            params = [deck_id]
            query = """
                SELECT change_date, change_type, old_level, new_level
                FROM level_history
                WHERE deck_id = ?
            """
            
            if start_date:
                query += " AND change_date >= ?"
                params.append(start_date)
            
            if end_date:
                # Ändere den end_date-Filter, um den gesamten Tag einzuschließen
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
                end_date_with_time = (end_date_obj + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
                query += " AND change_date <= ?"
                params.append(end_date_with_time)
            
            query += " ORDER BY change_date ASC"
            
            print(f"Study Tracker: Level-Historie Abfrage: {query} mit Parametern {params}")
            
            cursor = self.conn.execute(query, params)
            level_history_data = []
            
            for history_item in cursor.fetchall():
                try:
                    if len(history_item) >= 4:
                        change_date, change_type, old_level, new_level = history_item
                        
                        # Debug-Info
                        print(f"Study Tracker: Level-Änderung gefunden: {change_date}, {change_type}, {old_level} -> {new_level}")
                        
                        level_history_data.append({
                            'date': change_date,
                            'change_type': change_type,
                            'old_level': old_level,
                            'new_level': new_level
                        })
                except Exception as e:
                    print(f"Study Tracker: Fehler bei Verarbeitung von Level-Historie: {e}")
                    continue
            
            print(f"Study Tracker: Insgesamt {len(level_history_data)} Level-Änderungen gefunden")
            return level_history_data
        except Exception as e:
            print(f"Study Tracker: Fehler beim Abrufen der Level-Historie: {e}")
            traceback.print_exc()
            return []
    
    def save_streak_record(self, deck_id, streak):
        """Speichert einen neuen Streak-Rekord"""
        try:
            with self.conn:
                # Prüfe, ob es bereits einen höheren Rekord gibt
                cursor = self.conn.execute("""
                    SELECT record FROM streak_records
                    WHERE deck_id = ?
                    ORDER BY record DESC LIMIT 1
                """, (deck_id,))
                result = cursor.fetchone()
                
                if not result or streak > result[0]:
                    self.conn.execute("""
                        INSERT INTO streak_records
                        (deck_id, record, date)
                        VALUES (?, ?, ?)
                    """, (deck_id, streak, datetime.now().strftime("%Y-%m-%d")))
                    return True
            return False
        except Exception as e:
            print(f"Fehler beim Speichern des Streak-Rekords: {e}")
            self.handle_db_error(e)
            return False
    
    def get_streak_record(self, deck_id):
        """Holt den höchsten Streak-Rekord für ein Deck"""
        try:
            cursor = self.conn.execute("""
                SELECT record FROM streak_records
                WHERE deck_id = ?
                ORDER BY record DESC LIMIT 1
            """, (deck_id,))
            result = cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            print(f"Fehler beim Abrufen des Streak-Rekords: {e}")
            return 0
    
    def save_validation_code(self, card_id, deck_id, code, page_number=0, chat_link=None, card_title=None, date=None):
        """
        Saves a validation code with improved duplicate handling.
        
        Args:
            card_id: ID of the card
            deck_id: ID of the deck
            code: The validation code (e.g. 9080)
            page_number: Optional, page number
            chat_link: Optional, link to ChatGPT
            card_title: Optional, title of the card
            date: Optional, specific date for the code; uses current date if not provided
            
        Returns:
            bool: True on success, False on error
        """
        try:
            # Ensure card_id is always a string
            card_id_str = str(card_id) if card_id is not None else None
            
            # Ensure deck_id is always an integer
            deck_id_int = int(deck_id) if deck_id is not None else None
            
            if card_id_str is None:
                print("Study Tracker: Warning: card_id is None, validation code cannot be saved")
                return False
            
            if not code or len(code) < 4:
                print(f"Study Tracker: Warning: Invalid code format: {code}")
                return False
            
            # Parse the code for correctness and difficulty
            correct_percent = int(code[:2]) if len(code) >= 2 else 0
            difficulty = int(code[2:4]) if len(code) >= 4 else 0
            
            # Use provided date or current date
            if date:
                current_date = date
            else:
                current_date = datetime.now().strftime("%Y-%m-%d")
            
            # Create unique ID for this validation code entry
            unique_key = f"{card_id_str}_{current_date}_{code}"
            
            # Check if an identical entry already exists
            cursor = self.conn.execute("""
                SELECT id FROM validation_codes
                WHERE card_id = ? AND date = ? AND code = ?
            """, (card_id_str, current_date, code))
            
            result = cursor.fetchone()
            if result:
                # Update existing entry if changes are needed
                update_needed = False
                
                # Get current entry
                cursor = self.conn.execute("""
                    SELECT card_title, chat_link
                    FROM validation_codes
                    WHERE id = ?
                """, (result[0],))
                
                current_data = cursor.fetchone()
                
                if current_data:
                    current_title, current_link = current_data
                    
                    # Check if updates are needed
                    if ((card_title and card_title != current_title) or 
                        (chat_link and chat_link != current_link)):
                        update_needed = True
                
                if update_needed:
                    self.conn.execute("""
                        UPDATE validation_codes
                        SET chat_link = COALESCE(?, chat_link),
                            card_title = COALESCE(?, card_title),
                            correct_percent = ?,
                            difficulty = ?,
                            page_number = ?
                        WHERE id = ?
                    """, (
                        chat_link,
                        card_title,
                        correct_percent,
                        difficulty,
                        page_number,
                        result[0]
                    ))
                    self.conn.commit()
                    print(f"Study Tracker: Updated validation code for card {card_id_str}: {code}")
                
                return True  # Already exists, potentially updated
                
            # Save new validation code
            self.conn.execute("""
                INSERT INTO validation_codes
                (card_id, deck_id, date, code, correct_percent, difficulty, page_number, chat_link, card_title, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                card_id_str,
                deck_id_int,
                current_date,
                code,
                correct_percent,
                difficulty,
                page_number,
                chat_link,
                card_title,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            self.conn.commit()
            
            print(f"Study Tracker: New validation code saved for card {card_id_str}: {code} with date {current_date}")
            return True
        except Exception as e:
            print(f"Study Tracker: Error saving validation code for card {card_id}: {e}")
            traceback.print_exc()
            self.handle_db_error(e)
            return False
    
    def get_card_id_by_title(self, title_fragment):
        """
        Findet eine Karten-ID anhand eines Titelteils (für Debugging und Fehlersuche)
        
        Args:
            title_fragment: Teil des Titels
        
        Returns:
            str: Karten-ID oder None, wenn nicht gefunden
        """
        try:
            cursor = self.conn.execute("""
                SELECT card_id FROM validation_codes 
                WHERE card_title LIKE ? 
                UNION 
                SELECT card_id FROM chat_links 
                WHERE card_title LIKE ?
                LIMIT 1
            """, (f'%{title_fragment}%', f'%{title_fragment}%'))
            
            result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            print(f"Fehler beim Suchen der Karten-ID mit Titel '{title_fragment}': {e}")
            return None
    
    def get_validation_codes(self, deck_id, start_date=None, end_date=None, card_id=None):
        """
        Holt Validierungscodes für ein Deck und optional einen Zeitraum mit verbessertem Logging
        
        Args:
            deck_id: ID des Decks
            start_date: Optional, frühestes zu berücksichtigendes Datum
            end_date: Optional, spätestes zu berücksichtigendes Datum
            card_id: Optional, ID der Karte
            
        Returns:
            list: Liste von Validierungscode-Tupeln
        """
        try:
            params = []
            query = """
                SELECT date, code, correct_percent, difficulty, page_number, chat_link, card_id, card_title
                FROM validation_codes
                WHERE 1=1
            """
            
            if deck_id is not None:
                query += " AND deck_id = ?"
                params.append(deck_id)
            
            if card_id:
                query += " AND card_id = ?"
                params.append(str(card_id))
            
            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            
            query += " ORDER BY date ASC"
            
            print(f"Ausführen der Abfrage: {query} mit Parametern: {params}")
            
            cursor = self.conn.execute(query, params)
            results = cursor.fetchall()
            
            print(f"Abfrage der Validierungscodes ergab {len(results)} Ergebnisse")
            for result in results:
                print(f"Code: {result[1]} für Karte {result[6]}")
            
            return results
        except Exception as e:
            print(f"Fehler beim Abrufen der Validierungscodes: {e}")
            traceback.print_exc()
            return []
    
    def save_chat_link(self, card_id, link, deck_id=None, card_title=None):
        """Speichert einen ChatGPT-Link für eine Karte mit robuster URL-Formatierung"""
        try:
            # Stelle sicher, dass card_id immer ein String ist
            card_id_str = str(card_id) if card_id is not None else None
            
            if card_id_str is None:
                print("Study Tracker: Warnung: card_id ist None, ChatGPT-Link kann nicht gespeichert werden")
                return False
            
            # Stelle sicher, dass der Link vollständig und korrekt ist
            if link:
                # Entferne versehentlich angehängte HTML-Tags
                if "<a href=" in link:
                    link = re.sub(r'<a href="([^"]+)".*', r'\1', link)
                
                # Entferne eventuelle Anführungszeichen am Ende
                link = link.rstrip('"\'')
                
                # Stelle sicher, dass der Link vollständig ist und mit https:// beginnt
                if not link.startswith(('http://', 'https://')):
                    link = 'https://' + link
                    
            print(f"Study Tracker: Speichere ChatGPT-Link: {link} für Karte {card_id_str}")
            
            with self.conn:
                self.conn.execute("""
                    INSERT OR REPLACE INTO chat_links
                    (card_id, deck_id, link, card_title, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    card_id_str,
                    deck_id,
                    link,
                    card_title,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
                
                # Verifiziere den gespeicherten Link
                cursor = self.conn.execute("SELECT link FROM chat_links WHERE card_id = ?", (card_id_str,))
                saved_link = cursor.fetchone()
                if saved_link:
                    print(f"Study Tracker: Link erfolgreich gespeichert: {saved_link[0]}")
                
            return True
        except Exception as e:
            print(f"Study Tracker: Fehler beim Speichern des ChatGPT-Links für Karte {card_id}: {e}")
            self.handle_db_error(e)
        return False
    
    def get_chat_link(self, card_id):
        """Holt den ChatGPT-Link für eine Karte mit robuster ID-Konvertierung"""
        try:
            # Stelle sicher, dass card_id immer ein String ist
            card_id_str = str(card_id) if card_id is not None else None
            
            if card_id_str is None:
                return None
                
            cursor = self.conn.execute("""
                SELECT link FROM chat_links
                WHERE card_id = ?
            """, (card_id_str,))
            result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            print(f"Study Tracker: Fehler beim Abrufen des ChatGPT-Links für Karte {card_id}: {e}")
            return None
    
    def save_studied_card(self, date, card_id, deck_id, review_time):
        """Speichert eine gelernte Karte"""
        try:
            with self.conn:
                self.conn.execute("""
                    INSERT OR REPLACE INTO studied_cards
                    (date, card_id, deck_id, review_time)
                    VALUES (?, ?, ?, ?)
                """, (date, str(card_id), deck_id, review_time))
            return True
        except Exception as e:
            print(f"Fehler beim Speichern der gelernten Karte: {e}")
            self.handle_db_error(e)
            return False
    
    def get_studied_cards(self, date, deck_id=None):
        """Holt gelernte Karten für ein Datum und optional ein Deck"""
        try:
            params = [date]
            query = """
                SELECT card_id, deck_id, review_time
                FROM studied_cards
                WHERE date = ?
            """
            
            if deck_id:
                query += " AND deck_id = ?"
                params.append(deck_id)
            
            cursor = self.conn.execute(query, params)
            return cursor.fetchall()
        except Exception as e:
            print(f"Fehler beim Abrufen der gelernten Karten: {e}")
            return []
    
    def export_backup(self, backup_path, password=None):
        """Erstellt ein Backup der Datenbank"""
        try:
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            with sqlite3.connect(backup_path) as backup_db:
                self.conn.backup(backup_db)
                
            if password:
                if not self._encrypt_file(backup_path, password):
                    return False
            return True
        except Exception as e:
            print(f"Backup fehlgeschlagen: {e}")
            self.handle_db_error(e)
            return False
    
    def import_backup(self, backup_path, password=None):
        """Importiert ein Backup"""
        try:
            if password:
                # Erstelle temporäre Kopie für Entschlüsselung
                temp_path = backup_path + '.temp'
                shutil.copy2(backup_path, temp_path)
                
                if not self._decrypt_file(temp_path, password):
                    os.remove(temp_path)
                    return False
                    
                # Importiere entschlüsselte Datei
                with sqlite3.connect(temp_path) as backup_db:
                    backup_db.backup(self.conn)
                    
                os.remove(temp_path)
            else:
                with sqlite3.connect(backup_path) as backup_db:
                    backup_db.backup(self.conn)
            return True
        except Exception as e:
            print(f"Import fehlgeschlagen: {e}")
            self.handle_db_error(e)
            return False
    
    def _encrypt_file(self, file_path, password):
        """Verschlüsselt eine Datei mit einem Passwort"""
        try:
            # Erstelle einen Hash des Passworts
            key = hashlib.sha256(password.encode()).digest()
            
            # Lese die Original-Datei
            with open(file_path, 'rb') as f:
                data = f.read()
            
            # Verschlüssele die Daten (einfache XOR-Verschlüsselung)
            encrypted_data = bytearray()
            for i in range(len(data)):
                encrypted_data.append(data[i] ^ key[i % len(key)])
            
            # Speichere die verschlüsselten Daten
            with open(file_path, 'wb') as f:
                f.write(encrypted_data)
            return True
        except Exception as e:
            print(f"Verschlüsselung fehlgeschlagen: {e}")
            return False
    
    def _decrypt_file(self, file_path, password):
        """Entschlüsselt eine Datei mit einem Passwort"""
        # Bei XOR ist Entschlüsselung gleich Verschlüsselung
        return self._encrypt_file(file_path, password)

    def get_chat_links_by_deck(self, deck_id, start_date=None, end_date=None):
        """Holt alle ChatGPT-Links für ein bestimmtes Deck"""
        try:
            params = [deck_id]
            query = """
                SELECT card_id, link, card_title, updated_at
                FROM chat_links
                WHERE deck_id = ?
            """
            
            if start_date:
                query += " AND updated_at >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND updated_at <= ?"
                params.append(end_date)
            
            cursor = self.conn.execute(query, params)
            return cursor.fetchall()
        except Exception as e:
            print(f"Fehler beim Abrufen der ChatGPT-Links: {e}")
            return []

    def get_card_chat_link(self, card_id):
        """Gets the latest ChatGPT link for a specific card with improved error handling"""
        try:
            if not card_id:
                return None
                
            cursor = self.conn.execute("""
                SELECT link FROM chat_links
                WHERE card_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
            """, (str(card_id),))
            result = cursor.fetchone()
            
            if result and result[0]:
                return result[0]
                
            # If no link in chat_links, look in validation_codes
            cursor = self.conn.execute("""
                SELECT chat_link FROM validation_codes
                WHERE card_id = ? AND chat_link IS NOT NULL AND chat_link != ''
                ORDER BY created_at DESC
                LIMIT 1
            """, (str(card_id),))
            result = cursor.fetchone()
            
            return result[0] if result and result[0] else None
        except Exception as e:
            print(f"Error retrieving ChatGPT link for card {card_id}: {e}")
            return None

    def get_validation_codes_for_card(self, card_id, start_date=None, end_date=None):
        """
        Holt alle Validierungscodes für eine bestimmte Karte direkt aus der Datenbank
        mit verbesserter Fehlerbehandlung und Debug-Ausgaben
        
        Args:
            card_id: ID der Karte
            start_date: Optional, frühestes zu berücksichtigendes Datum
            end_date: Optional, spätestes zu berücksichtigendes Datum
            
        Returns:
            list: Liste von Validierungscode-Tupeln für die Karte
        """
        try:
            if not card_id:
                return []
            
            # Konvertiere card_id immer zu String für konsistente Vergleiche
            card_id_str = str(card_id)
            
            print(f"Study Tracker: Suche Validierungscodes für Karte {card_id_str}")
            
            params = [card_id_str]
            query = """
                SELECT date, code, correct_percent, difficulty, page_number, chat_link, card_id, card_title
                FROM validation_codes
                WHERE card_id = ?
            """
            
            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            
            query += " ORDER BY date ASC"
            
            print(f"Study Tracker: Ausführe Query: {query} mit Parametern {params}")
            
            cursor = self.conn.execute(query, params)
            results = cursor.fetchall()
            
            print(f"Study Tracker: Gefunden: {len(results)} Validierungscodes für Karte {card_id_str}")
            
            # Für detaillierte Debugging: Zeige die ersten 3 Ergebnisse
            for i, result in enumerate(results[:3]):
                if result:
                    print(f"  Code {i+1}: {result[0]} - {result[1]}")
            
            return results
        except Exception as e:
            print(f"Study Tracker: Fehler beim Abrufen der Validierungscodes für Karte {card_id}: {e}")
            traceback.print_exc()
            return []
    
    def get_studied_cards_with_details(self, date_str, deck_id=None):
        """Holt alle gelernten Karten mit zugehörigen Titeln und Links für ein Datum"""
        try:
            params = [date_str]
            query = """
                SELECT s.card_id, s.deck_id, s.review_time,
                    (SELECT c.link FROM chat_links c WHERE c.card_id = s.card_id) as chat_link
                FROM studied_cards s
                WHERE s.date = ?
            """
            
            if deck_id:
                query += " AND s.deck_id = ?"
                params.append(deck_id)
            
            cursor = self.conn.execute(query, params)
            cards = cursor.fetchall()
            
            # Ergänze Kartentitel
            enhanced_cards = []
            for card in cards:
                card_id, card_deck_id, review_time, chat_link = card
                
                # Hole Kartentitel
                title_query = """
                    SELECT card_title FROM validation_codes WHERE card_id = ? AND card_title IS NOT NULL
                    UNION
                    SELECT card_title FROM chat_links WHERE card_id = ? AND card_title IS NOT NULL
                    LIMIT 1
                """
                cursor = self.conn.execute(title_query, (str(card_id), str(card_id)))
                title_result = cursor.fetchone()
                
                card_title = title_result[0] if title_result else "Unbekannte Karte"
                
                enhanced_cards.append({
                    'card_id': card_id,
                    'deck_id': card_deck_id,
                    'review_time': review_time,
                    'chat_link': chat_link,
                    'card_title': card_title
                })
            
            return enhanced_cards
        except Exception as e:
            print(f"Fehler beim Abrufen der gelernten Karten mit Details: {e}")
            return []
    
    def clean_duplicate_level_entries(self):
        """Bereinigt doppelte Level-Einträge in der Datenbank"""
        try:
            print("Study Tracker: Bereinige doppelte Level-Einträge...")
            
            # Behalte nur den ersten Eintrag pro Tag und Typ
            self.conn.execute("""
                DELETE FROM level_history
                WHERE id NOT IN (
                    SELECT MIN(id)
                    FROM level_history
                    GROUP BY date(change_date), deck_id, change_type
                )
            """)
            
            self.conn.commit()
            
            cursor = self.conn.execute("SELECT changes()")
            deleted_count = cursor.fetchone()[0]
            
            print(f"Study Tracker: {deleted_count} doppelte Einträge entfernt")
            return deleted_count
        except Exception as e:
            print(f"Study Tracker: Fehler bei der Bereinigung doppelter Level-Einträge: {e}")
            traceback.print_exc()
            return 0

    def update_card_deck(self, card_id, new_deck_id):
        """
        Aktualisiert die Deck-ID einer Karte in allen relevanten Tabellen.
        Optimiert für wöchentliche Verschiebungen einzelner Karten.
        
        Args:
            card_id: ID der Karte
            new_deck_id: Neue Deck-ID
        """
        try:
            card_id_str = str(card_id)
            
            # Hole aktuelle Deck-ID aus der Datenbank
            cursor = self.conn.execute("""
                SELECT deck_id FROM validation_codes WHERE card_id = ?
                UNION
                SELECT deck_id FROM chat_links WHERE card_id = ?
                UNION
                SELECT deck_id FROM studied_cards WHERE card_id = ?
                LIMIT 1
            """, (card_id_str, card_id_str, card_id_str))
            
            current_deck_id = None
            result = cursor.fetchone()
            if result:
                current_deck_id = result[0]
            
            # Überprüfe, ob sich die Deck-ID tatsächlich geändert hat
            if current_deck_id is not None and current_deck_id == new_deck_id:
                return True  # Keine Änderung notwendig
                
            # Aktualisiere Validierungscodes
            with self.conn:
                # Validierungscodes aktualisieren
                updated_validation = self.conn.execute("""
                    UPDATE validation_codes
                    SET deck_id = ?
                    WHERE card_id = ?
                """, (new_deck_id, card_id_str)).rowcount
                
                # ChatGPT-Links aktualisieren
                updated_links = self.conn.execute("""
                    UPDATE chat_links
                    SET deck_id = ?
                    WHERE card_id = ?
                """, (new_deck_id, card_id_str)).rowcount
                
                # Gelernte Karten aktualisieren
                updated_studied = self.conn.execute("""
                    UPDATE studied_cards
                    SET deck_id = ?
                    WHERE card_id = ?
                """, (new_deck_id, card_id_str)).rowcount
            
            print(f"Study Tracker: Karte {card_id_str} wurde verschoben: {current_deck_id} -> {new_deck_id}")
            print(f"Aktualisiert: {updated_validation} Validierungscodes, {updated_links} ChatGPT-Links, {updated_studied} Lerneinträge")
            return True
        except Exception as e:
            print(f"Study Tracker: Fehler beim Aktualisieren der Deck-ID: {e}")
            traceback.print_exc()
            return False

    def efficient_card_tracking(self):
        """
        Effiziente Methode zum Tracking verschobener Karten.
        Optimiert für die regelmäßige Verschiebung weniger Karten.
        Wird vor der Berichterstellung aufgerufen, um sicherzustellen, 
        dass die Deck-Zuordnungen korrekt sind.
        """
        if not mw or not mw.col:
            print("Study Tracker: Anki-Sammlung nicht verfügbar")
            return False
            
        try:
            print("Study Tracker: Starte effizientes Karten-Tracking")
            
            # Priorisiere kürzlich gelernte Karten für das Tracking
            cursor = self.conn.execute("""
                SELECT DISTINCT card_id FROM studied_cards 
                WHERE date >= date('now', '-90 days')
                LIMIT 100
            """)
            
            recent_card_ids = [row[0] for row in cursor.fetchall()]
            
            # Füge wichtige Karten mit Validierungscodes hinzu
            cursor = self.conn.execute("""
                SELECT DISTINCT card_id FROM validation_codes
                LIMIT 100
            """)
            
            validation_card_ids = [row[0] for row in cursor.fetchall()]
            
            # Kombiniere die Listen und entferne Duplikate
            all_card_ids = list(set(recent_card_ids + validation_card_ids))
            
            print(f"Study Tracker: Überprüfe {len(all_card_ids)} wichtige Karten")
            
            # Verfolge jede Karte in Anki
            updated_count = 0
            for card_id in all_card_ids:
                try:
                    card = mw.col.get_card(int(card_id))
                    if card:
                        # Aktualisiere Deck-ID in der Datenbank
                        if self.update_card_deck(card_id, card.did):
                            updated_count += 1
                            
                        # Hole den aktuellen Kartentitel und aktualisiere ihn in der Datenbank
                        note = card.note()
                        title = None
                        
                        # Versuche Vorderseite oder ähnliche Felder
                        for field in ['Vorderseite', 'Front', 'Question', 'Frage']:
                            if field in note:
                                title = note[field]
                                break
                        
                        # Fallback: Erstes Feld
                        if not title and note.keys():
                            title = note[note.keys()[0]]
                        
                        if title:
                            # Bereinige und kürze den Titel
                            title = clean_html(title)
                            if len(title) > 50:
                                title = title[:47] + "..."
                            
                            # Aktualisiere den Titel in der Datenbank
                            with self.conn:
                                self.conn.execute("""
                                    UPDATE validation_codes
                                    SET card_title = ?
                                    WHERE card_id = ?
                                """, (title, card_id))
                                
                                self.conn.execute("""
                                    UPDATE chat_links
                                    SET card_title = ?
                                    WHERE card_id = ?
                                """, (title, card_id))
                except Exception as e:
                    print(f"Study Tracker: Fehler beim Tracking der Karte {card_id}: {e}")
                    continue
            
            print(f"Study Tracker: {updated_count} Karten wurden synchronisiert")
            return updated_count > 0
        except Exception as e:
            print(f"Study Tracker: Fehler beim Karten-Tracking: {e}")
            traceback.print_exc()
            return False

    def update_all_validation_code_links(self):
        """
        Aktualisiert die Verknüpfung zwischen Validierungscodes und ChatGPT-Links.
        Besonders wichtig für verschobene Karten.
        """
        try:
            print("Study Tracker: Aktualisiere Verknüpfungen zwischen Validierungscodes und ChatGPT-Links")
            
            # Hole alle ChatGPT-Links
            cursor = self.conn.execute("""
                SELECT card_id, link FROM chat_links
                WHERE link IS NOT NULL AND link != ''
            """)
            
            link_updates = 0
            for card_id, link in cursor.fetchall():
                # Aktualisiere Validierungscodes mit dem Link
                updated = self.conn.execute("""
                    UPDATE validation_codes
                    SET chat_link = ?
                    WHERE card_id = ? AND (chat_link IS NULL OR chat_link = '')
                """, (link, card_id)).rowcount
                
                if updated > 0:
                    link_updates += updated
            
            print(f"Study Tracker: {link_updates} Validierungscodes mit ChatGPT-Links verknüpft")
            return link_updates > 0
        except Exception as e:
            print(f"Study Tracker: Fehler bei der Link-Aktualisierung: {e}")
            traceback.print_exc()
            return False

    def prepare_for_report(self, deck_id, start_date, end_date):
        """
        Bereitet die Datenbank für die Berichterstellung vor.
        Diese Methode sorgt dafür, dass die Berichtsdaten korrekt sind.
        
        Args:
            deck_id: ID des Decks für den Bericht
            start_date: Startdatum im Format YYYY-MM-DD
            end_date: Enddatum im Format YYYY-MM-DD
        """
        try:
            print(f"Study Tracker: Bereite Daten für Bericht vor (Deck {deck_id}, {start_date} bis {end_date})")
            
            # 1. Tracking verschobener Karten
            self.efficient_card_tracking()
            
            # 2. Aktualisiere ChatGPT-Links für Validierungscodes
            self.update_all_validation_code_links()
            
            # 3. Vereinheitliche Kartentitel zwischen validation_codes und chat_links
            self.conn.execute("""
                UPDATE validation_codes AS v
                SET card_title = (
                    SELECT c.card_title FROM chat_links AS c
                    WHERE c.card_id = v.card_id AND c.card_title IS NOT NULL AND c.card_title != ''
                    LIMIT 1
                )
                WHERE EXISTS (
                    SELECT 1 FROM chat_links AS c
                    WHERE c.card_id = v.card_id AND c.card_title IS NOT NULL AND c.card_title != ''
                )
                AND (v.card_title IS NULL OR v.card_title = '' OR v.card_title LIKE 'Karte %')
            """)
            
            # 4. Aktualisiere fehlende Deck-IDs für den gewählten Zeitraum
            self.conn.execute("""
                UPDATE validation_codes
                SET deck_id = ?
                WHERE deck_id IS NULL AND date BETWEEN ? AND ?
            """, (deck_id, start_date, end_date))
            
            self.conn.commit()
            print("Study Tracker: Berichtsvorbereitung abgeschlossen")
            return True
        except Exception as e:
            print(f"Study Tracker: Fehler bei der Berichtsvorbereitung: {e}")
            traceback.print_exc()
            return False  

class LevelSystem:
    """Implementierung des Levelsystems basierend auf 7-Tage-Abschnitten"""
    
    def __init__(self, db, deck_id=None):
        self.db = db
        self.deck_id = deck_id if deck_id is not None else 0
        self.current_level = 1
        self.period_start_date = datetime.now().date()
        self.load_progress()
    
    def load_progress(self):
        """Lädt den aktuellen Level-Fortschritt aus der Datenbank"""
        progress = self.db.get_level_progress(self.deck_id)
        if progress:
            self.current_level = progress['level']
            self.period_start_date = progress['start_date']
        else:
            # Initialisiere neuen Fortschritt
            self.db.save_level_progress(
                self.deck_id,
                self.current_level,
                self.period_start_date
            )
    
    def check_daily_goal(self, date=None):
        """Überprüft, ob das tägliche Lernziel erreicht wurde"""
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        stats = self.db.get_daily_stats(date, self.deck_id)
        cards_due = stats['cards_due']
        cards_studied = stats['cards_studied']
        
        # Ziel erreicht, wenn keine Karten fällig waren oder alle fälligen Karten gelernt wurden
        if cards_due == 0 or (cards_due > 0 and cards_studied >= cards_due):
            return True
        return False
    
    def count_successful_days(self):
        """Zählt erfolgreiche Lerntage im aktuellen 7-Tage-Abschnitt"""
        if not self.period_start_date:
            return 0
        
        period_end = self.period_start_date + timedelta(days=6)
        current_date = self.period_start_date
        successful_days = 0
        
        while current_date <= period_end and current_date <= datetime.now().date():
            if self.check_daily_goal(current_date.strftime("%Y-%m-%d")):
                successful_days += 1
            current_date += timedelta(days=1)
        
        return successful_days
    
    def check_period_completion(self):
        """
        Überprüft, ob der aktuelle 7-Tage-Abschnitt abgeschlossen ist und
        führt entsprechende Level-Änderungen durch.
        """
        today = datetime.now().date()
        
        # NEU: Prüfe, ob in den letzten 3 Tagen bereits ein neuer Abschnitt gestartet wurde
        try:
            three_days_ago = today - timedelta(days=3)
            cursor = self.db.conn.execute("""
                SELECT COUNT(*) FROM level_history
                WHERE deck_id = ? AND date(change_date) >= ? 
                AND change_type IN ('new_period', 'reset_period', 'early_completion', 'init')
            """, (self.deck_id, three_days_ago.strftime("%Y-%m-%d")))
            
            recent_period_changes = cursor.fetchone()[0]
            if recent_period_changes > 0:
                print(f"Study Tracker: In den letzten 3 Tagen wurde bereits ein neuer Abschnitt für Deck {self.deck_id} gestartet. Überspringe Periodencheck.")
                return False
        except Exception as e:
            print(f"Study Tracker: Fehler bei der Prüfung auf kürzlich gestartete Abschnitte: {e}")
        
        # Bestehende Prüfung für heute beibehalten
        try:
            # Prüfe speziell nach Periodenänderungen für heute (new_period, reset_period, early_completion)
            cursor = self.db.conn.execute("""
                SELECT COUNT(*) FROM level_history
                WHERE deck_id = ? AND change_date LIKE ? AND change_type IN ('new_period', 'reset_period', 'early_completion')
            """, (self.deck_id, f"{today.strftime('%Y-%m-%d')}%"))
            
            count = cursor.fetchone()[0]
            if count > 0:
                print(f"Study Tracker: Heute wurde bereits ein neuer Abschnitt für Deck {self.deck_id} gestartet. Überspringe Periodencheck.")
                return False
        except Exception as e:
            print(f"Study Tracker: Fehler bei der Prüfung auf bestehende Periodeneinträge: {e}")
        
        days_passed = (today - self.period_start_date).days
        
        # Debug-Ausgabe zum besseren Verständnis der Abschnittsprüfung
        print(f"Study Tracker: Abschnittsprüfung für Deck {self.deck_id}")
        print(f"  - Heutiges Datum: {today}")
        print(f"  - Abschnitt-Startdatum: {self.period_start_date}")
        print(f"  - Tage seit Abschnittsbeginn: {days_passed}")
        
        # Wenn 7 Tage vorbei sind, bewerte den Abschnitt
        if days_passed >= 7:
            print(f"Study Tracker: 7-Tage-Abschnitt abgeschlossen, bewerte Fortschritt...")
            successful_days = self.count_successful_days()
            old_level = self.current_level
            
            if successful_days >= 5:
                self.level_up()
                print(f"Study Tracker: Level Up! {old_level} -> {self.current_level}")
            else:
                self.level_down()
                print(f"Study Tracker: Level Down! {old_level} -> {self.current_level}")
                    
            # Starte neuen Abschnitt
            self.period_start_date = today
            self.db.save_level_progress(self.deck_id, self.current_level, self.period_start_date)
            
            # Speichere einen Eintrag für neuen Abschnitt, auch wenn Level gleich bleibt
            if old_level == self.current_level:
                result = self.db.save_level_change(self.deck_id, "new_period", old_level, self.current_level)
                print(f"Study Tracker: Neuer Lernabschnitt auf Level {self.current_level} begonnen (Erfolg: {result})")
            
            return True
        
        # Prüfe, ob es noch möglich ist, 5 Lerntage zu erreichen
        remaining_days = 7 - days_passed
        successful_days = self.count_successful_days()
        needed_days = 5 - successful_days
        
        print(f"  - Erfolgreiche Lerntage bisher: {successful_days}/5")
        print(f"  - Verbleibende Tage im Abschnitt: {remaining_days}")
        print(f"  - Benötigte erfolgreiche Tage: {needed_days}")
        
        if needed_days > remaining_days:
            # Lernziel kann nicht mehr erreicht werden, setze Abschnitt zurück
            message = "Das Lernziel kann in diesem Abschnitt nicht mehr erreicht werden. Ein neuer Abschnitt beginnt."
            old_level = self.current_level
            
            if self.current_level > 1:
                self.level_down()
                message = f"Das Lernziel wurde nicht erreicht. Du bist auf Level {self.current_level} zurückgefallen."
            
            # Starte neuen Abschnitt
            self.period_start_date = today
            self.db.save_level_progress(self.deck_id, self.current_level, self.period_start_date)
            
            # Speichere einen Eintrag für den abgebrochenen/zurückgesetzten Abschnitt
            self.db.save_level_change(self.deck_id, "reset_period", old_level, self.current_level)
            print(f"Study Tracker: Abschnitt vorzeitig zurückgesetzt, neues Level: {self.current_level}")
            
            return message
        
        # Prüfe, ob heute der 5. erfolgreiche Tag ist
        if successful_days == 5 and self.check_daily_goal():
            old_level = self.current_level
            self.level_up()
            # Starte neuen Abschnitt
            self.period_start_date = today + timedelta(days=1)  # Neuer Abschnitt beginnt morgen
            self.db.save_level_progress(self.deck_id, self.current_level, self.period_start_date)
            
            # Speichere einen Eintrag für vorzeitiges Erreichen des Ziels
            self.db.save_level_change(self.deck_id, "early_completion", old_level, self.current_level)
            print(f"Study Tracker: Frühzeitiges Level-Up auf Level {self.current_level}")
            
            return "level_up"
                
        return False
    
    def level_up(self):
        """Führt ein Level-Up durch"""
        old_level = self.current_level
        self.current_level += 1
        self.db.save_level_change(self.deck_id, "up", old_level, self.current_level)
        print(f"Level Up! {old_level} -> {self.current_level}")
        return True
    
    def level_down(self):
        """Führt ein Level-Down durch, wenn möglich"""
        if self.current_level > 1:
            old_level = self.current_level
            self.current_level -= 1
            self.db.save_level_change(self.deck_id, "down", old_level, self.current_level)
            print(f"Level Down! {old_level} -> {self.current_level}")
            return True
        return False
    
    def get_progress_message(self):
        """Generiert eine Nachricht zum aktuellen Fortschritt"""
        if not self.period_start_date:
            return f"Level {self.current_level}: Kein aktiver Lernabschnitt."
        
        days_passed = (datetime.now().date() - self.period_start_date).days
        remaining_days = max(0, 7 - days_passed)
        successful_days = self.count_successful_days()
        needed_days = max(0, 5 - successful_days)
        
        if needed_days <= remaining_days:
            return f"Level {self.current_level}: Noch {needed_days} Lerntage in den nächsten {remaining_days} Tagen bis zum nächsten Level!"
        else:
            return f"Level {self.current_level}: Das Level-Ziel kann in diesem Zyklus nicht mehr erreicht werden."
    
    def calculate_progress_percent(self):
        """Berechnet den prozentualen Fortschritt zum nächsten Level"""
        successful_days = self.count_successful_days()
        return min(100, (successful_days / 5) * 100)


class ValidationCodeHandler:
    """Verbesserte Klasse zur Verwaltung von Validierungscodes mit robuster Kartentitel-Extraktion"""
    
    def __init__(self, db):
        self.db = db
    
    def save_code(self, card_id, deck_id, code, page_number=0, chat_link=None):
        """Speichert einen Validierungscode"""
        if not code or len(code) < 4:
            return False
        
        # Hole Kartentitel, wenn möglich
        card_title = self.get_card_title(card_id)
        
        return self.db.save_validation_code(
            card_id, deck_id, code, page_number, chat_link, card_title
        )
    
    def get_card_title(self, card_id):
        """Verbesserte Methode zum Ermitteln des Kartentitels mit besseren Fallbacks für verschobene Karten"""
        if not card_id:
            return "Unbekannte Karte"
                
        try:
            # 1. Versuche zuerst, den gespeicherten Titel aus der Datenbank zu holen
            cursor = self.db.conn.execute("""
                SELECT card_title FROM validation_codes 
                WHERE card_id = ? AND card_title IS NOT NULL AND card_title != ''
                ORDER BY created_at DESC LIMIT 1
            """, (str(card_id),))
            result = cursor.fetchone()
            if result and result[0] and len(result[0]) > 3:
                # Prüfe, ob der Titel wie eine ID aussieht (nur Zahlen)
                if not result[0].startswith("Karte ") and not result[0].isdigit():
                    return result[0]
            
            # 2. Versuche einen Titel aus der chat_links-Tabelle
            cursor = self.db.conn.execute("""
                SELECT card_title FROM chat_links 
                WHERE card_id = ? AND card_title IS NOT NULL AND card_title != ''
                LIMIT 1
            """, (str(card_id),))
            result = cursor.fetchone()
            if result and result[0] and len(result[0]) > 3:
                # Prüfe, ob der Titel wie eine ID aussieht (nur Zahlen)
                if not result[0].startswith("Karte ") and not result[0].isdigit():
                    return result[0]
            
            # 3. Versuche die Karte direkt aus Anki zu holen
            if hasattr(mw, 'col') and mw.col:
                try:
                    card = mw.col.get_card(int(card_id))
                    if card:
                        note = card.note()
                        title = None
                        
                        # Prioritätsreihenfolge für Feldnamen
                        field_names = ['Vorderseite', 'Front', 'Question', 'Frage']
                        
                        # Versuche bekannte Feldnamen
                        for field in field_names:
                            if field in note:
                                title = note[field]
                                break
                        
                        # Fallback: Erstes Feld verwenden
                        if not title and note.keys():
                            first_field = note.keys()[0]
                            title = note[first_field]
                            
                        if title:
                            # Bereinige HTML
                            title = clean_html(title)
                            
                            # Kürze lange Titel
                            if len(title) > 50:
                                title = title[:47] + "..."
                                
                            return title
                except Exception as e:
                    print(f"Fehler beim direkten Abrufen des Kartentitels: {e}")
            
            # 4. Versuche den Kartentitel unabhängig vom Deck zu finden
            try:
                cursor = self.db.conn.execute("""
                    SELECT card_title FROM validation_codes 
                    WHERE card_id = ? AND card_title IS NOT NULL AND card_title != '' AND card_title NOT LIKE 'Karte %'
                    LIMIT 1
                """, (str(card_id),))
                result = cursor.fetchone()
                if result and result[0]:
                    return result[0]
                    
                cursor = self.db.conn.execute("""
                    SELECT card_title FROM chat_links 
                    WHERE card_id = ? AND card_title IS NOT NULL AND card_title != '' AND card_title NOT LIKE 'Karte %'
                    LIMIT 1
                """, (str(card_id),))
                result = cursor.fetchone()
                if result and result[0]:
                    return result[0]
            except Exception as e:
                print(f"Fehler bei der unabhängigen Titelsuche: {e}")
            
            # 5. Formatierter Fallback mit Karten-ID für verschobene Karten
            short_id = str(card_id)[-8:] if len(str(card_id)) > 8 else str(card_id)
            return f"Karte #{short_id} (verschoben/archiviert)"
            
        except Exception as e:
            print(f"Fehler beim Abrufen des Kartentitels: {e}")
            short_id = str(card_id)[-8:] if len(str(card_id)) > 8 else str(card_id)
            return f"Karte #{short_id} (verschoben/archiviert)"
    
    def parse_code(self, code):
        """Parst einen Validierungscode in seine Komponenten mit verbesserter Robustheit"""
        if not code or not isinstance(code, str):
            return {'correct_percent': 0, 'difficulty': 0}
        
        # Stelle sicher, dass wir mit einem String arbeiten
        code_str = str(code).strip()
        
        if len(code_str) < 4:
            return {'correct_percent': 0, 'difficulty': 0}
        
        try:
            # Extrahiere die ersten 2 Zeichen als Korrektheitsprozent
            correct_percent_str = code_str[:2]
            correct_percent = int(correct_percent_str)
            
            # Extrahiere die nächsten 2 Zeichen als Schwierigkeit
            difficulty_str = code_str[2:4]
            difficulty = int(difficulty_str)
            
            # Validiere die Werte
            correct_percent = max(0, min(100, correct_percent))
            difficulty = max(0, min(10, difficulty))
            
            return {
                'correct_percent': correct_percent,
                'difficulty': difficulty
            }
        except ValueError:
            # Wenn die Konvertierung fehlschlägt, verwende Standardwerte
            return {'correct_percent': 0, 'difficulty': 0}
        except Exception as e:
            print(f"Fehler beim Parsen des Validierungscodes '{code_str}': {e}")
            return {'correct_percent': 0, 'difficulty': 0}
    
    def get_competency_data(self, deck_id, start_date=None, end_date=None):
        """
        Holt die Kompetenzdaten für einen Zeitraum mit verbesserter Fehlerbehandlung
        
        Returns:
            list: Liste von Tupeln (Datum, korrekter Prozentsatz, Schwierigkeit)
        """
        try:
            codes = self.db.get_validation_codes(deck_id, start_date, end_date)
            data = []
            
            for code in codes:
                try:
                    # Robuste Extraktion mit Fehlerbehandlung
                    if len(code) >= 4:
                        date, code_str, correct_percent, difficulty = code[:4]
                    elif len(code) >= 3:
                        date, code_str, correct_percent = code[:3]
                        difficulty = None
                    elif len(code) >= 2:
                        date, code_str = code[:2]
                        correct_percent = difficulty = None
                    else:
                        continue  # Überspringe unvollständige Daten
                    
                    # Validiere Werte
                    if correct_percent is None or difficulty is None:
                        parsed = self.parse_code(code_str)
                        correct_percent = parsed['correct_percent']
                        difficulty = parsed['difficulty']
                    
                    try:
                        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
                        data.append((date_obj, correct_percent, difficulty))
                    except ValueError:
                        # Wenn das Datum nicht im erwarteten Format ist, versuche alternative Formate
                        try:
                            date_obj = datetime.strptime(date, "%Y-%m-%d %H:%M:%S").date()
                            data.append((date_obj, correct_percent, difficulty))
                        except ValueError:
                            continue
                except Exception as e:
                    print(f"Fehler bei der Verarbeitung eines Validierungscodes: {e}")
                    continue
            
            return data
        except Exception as e:
            print(f"Fehler beim Abrufen der Kompetenzdaten: {e}")
            return []
    
    def get_card_validation_codes(self, card_id, start_date=None, end_date=None):
        """
        Fixed method to get validation codes for a specific card with proper filtering.
        
        Args:
            card_id: ID of the card
            start_date: Optional, earliest date to consider (YYYY-MM-DD)
            end_date: Optional, latest date to consider (YYYY-MM-DD)
            
        Returns:
            list: List of validation code dictionaries for the card
        """
        try:
            if not card_id:
                return []
            
            # Convert card_id to string for consistent handling
            card_id_str = str(card_id)
            
            print(f"Study Tracker: Getting validation codes for card {card_id_str}")
            
            # Direct SQL query for codes for this specific card only
            params = [card_id_str]
            query = """
                SELECT date, code, correct_percent, difficulty, page_number, chat_link, card_id, card_title
                FROM validation_codes
                WHERE card_id = ?
            """
            
            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            
            query += " ORDER BY date ASC"
            
            print(f"Study Tracker: Executing query: {query} with parameters {params}")
            
            cursor = self.db.conn.execute(query, params)
            results = cursor.fetchall()
            
            print(f"Study Tracker: Found {len(results)} validation codes for card {card_id_str}")
            
            # Convert to more usable format
            validation_codes = []
            for row in results:
                if len(row) >= 8:
                    date, code, correct_percent, difficulty, page_number, chat_link, result_card_id, card_title = row
                    
                    validation_codes.append({
                        'date': date,
                        'code': code,
                        'correct_percent': correct_percent,
                        'difficulty': difficulty,
                        'page_number': page_number,
                        'chat_link': chat_link,
                        'card_title': card_title
                    })
            
            return validation_codes
        except Exception as e:
            print(f"Study Tracker: Error getting validation codes for card {card_id}: {e}")
            traceback.print_exc()
            return []
    
    def calculate_competency_level(self, deck_id, days=30):
        """
        Berechnet das aktuelle Kompetenzniveau basierend auf den letzten Validierungscodes
        
        Returns:
            dict: {level, trend, avg_correct, max_difficulty}
        """
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        data = self.get_competency_data(deck_id, start_date, end_date)
        if not data:
            return {
                'level': 1,
                'trend': 'neutral',
                'avg_correct': 0,
                'max_difficulty': 0
            }
        
        # Sortiere nach Datum
        data.sort(key=lambda x: x[0])
        
        # Berechne Durchschnittswerte
        correct_values = [x[1] for x in data]
        difficulty_values = [x[2] for x in data]
        
        avg_correct = sum(correct_values) / len(correct_values) if correct_values else 0
        max_difficulty = max(difficulty_values) if difficulty_values else 0
        
        # Berechne Trend (letzte 3 Einträge)
        if len(data) >= 3:
            recent_correct = [x[1] for x in data[-3:]]
            if recent_correct[0] < recent_correct[1] < recent_correct[2]:
                trend = 'rising'
            elif recent_correct[0] > recent_correct[1] > recent_correct[2]:
                trend = 'falling'
            else:
                trend = 'stable'
        else:
            trend = 'neutral'
        
        # Berechne Level basierend auf Korrektheit und Schwierigkeit
        level = 1
        if avg_correct >= 90 and max_difficulty >= 5:
            level = 5
        elif avg_correct >= 80 and max_difficulty >= 4:
            level = 4
        elif avg_correct >= 70 and max_difficulty >= 3:
            level = 3
        elif avg_correct >= 60 and max_difficulty >= 2:
            level = 2
        
        return {
            'level': level,
            'trend': trend,
            'avg_correct': round(avg_correct, 1),
            'max_difficulty': max_difficulty
        }


class StreakCalculator:
    """Klasse zur Berechnung und Verwaltung von Lernstreaks"""
    
    def __init__(self, db, deck_id=None):
        self.db = db
        self.deck_id = deck_id
    
    def calculate_current_streak(self, start_date=None):
        """
        Berechnet die aktuelle Lernserie (Anzahl aufeinanderfolgender Tage mit Lernerfolg)
        
        Args:
            start_date: Optional, frühestes zu berücksichtigendes Datum
            
        Returns:
            int: Anzahl der aufeinanderfolgenden Tage mit Lernerfolg
        """
        today = datetime.now().date()
        current_date = today
        streak = 0
        
        # Setze Startdatum, wenn nicht angegeben
        if not start_date:
            # Verwende Installationsdatum aus den Einstellungen
            installation_date_str = self.db.get_setting('installation_date')
            if installation_date_str:
                try:
                    start_date = datetime.strptime(installation_date_str, "%Y-%m-%d").date()
                except ValueError:
                    start_date = today - timedelta(days=365)  # Fallback: 1 Jahr
            else:
                start_date = today - timedelta(days=365)  # Fallback: 1 Jahr
        elif isinstance(start_date, str):
            try:
                start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            except ValueError:
                start_date = today - timedelta(days=365)  # Fallback: 1 Jahr
        
        # Gehe rückwärts von heute, bis ein Tag ohne Lernerfolg gefunden wird
        while current_date >= start_date:
            date_str = current_date.strftime("%Y-%m-%d")
            stats = self.db.get_daily_stats(date_str, self.deck_id)
            
            cards_due = stats['cards_due']
            cards_studied = stats['cards_studied']
            
            if cards_due > 0 and cards_studied >= cards_due:
                streak += 1
                current_date -= timedelta(days=1)
            else:
                break
        
        return streak
    
    def calculate_longest_streak(self, start_date=None):
        """
        Berechnet die längste Lernserie seit dem Startdatum
        
        Args:
            start_date: Optional, frühestes zu berücksichtigendes Datum
            
        Returns:
            int: Längste Serie aufeinanderfolgender Tage mit Lernerfolg
        """
        # Prüfe, ob es einen gespeicherten Rekord gibt
        record = self.db.get_streak_record(self.deck_id)
        if record > 0:
            return record
        
        # Berechne den Rekord neu, wenn keiner gespeichert ist
        today = datetime.now().date()
        
        # Setze Startdatum, wenn nicht angegeben
        if not start_date:
            # Verwende Installationsdatum aus den Einstellungen
            installation_date_str = self.db.get_setting('installation_date')
            if installation_date_str:
                try:
                    start_date = datetime.strptime(installation_date_str, "%Y-%m-%d").date()
                except ValueError:
                    start_date = today - timedelta(days=365)  # Fallback: 1 Jahr
            else:
                start_date = today - timedelta(days=365)  # Fallback: 1 Jahr
        elif isinstance(start_date, str):
            try:
                start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            except ValueError:
                start_date = today - timedelta(days=365)  # Fallback: 1 Jahr
        
        current_date = start_date
        current_streak = 0
        longest_streak = 0
        
        # Gehe vorwärts von start_date bis heute
        while current_date <= today:
            date_str = current_date.strftime("%Y-%m-%d")
            stats = self.db.get_daily_stats(date_str, self.deck_id)
            
            cards_due = stats['cards_due']
            cards_studied = stats['cards_studied']
            
            if cards_due > 0 and cards_studied >= cards_due:
                current_streak += 1
                longest_streak = max(longest_streak, current_streak)
            else:
                current_streak = 0
            
            current_date += timedelta(days=1)
        
        # Speichere den berechneten Rekord
        if longest_streak > 0:
            self.db.save_streak_record(self.deck_id, longest_streak)
        
        return longest_streak
    
    def calculate_days_learned_percent(self, start_date=None):
        """
        Berechnet den Prozentsatz der Tage mit Lernerfolg seit dem Startdatum
        
        Args:
            start_date: Optional, frühestes zu berücksichtigendes Datum
            
        Returns:
            float: Prozentsatz der Tage mit Lernerfolg
        """
        today = datetime.now().date()
        
        # Setze Startdatum, wenn nicht angegeben
        if not start_date:
            # Verwende Installationsdatum aus den Einstellungen
            installation_date_str = self.db.get_setting('installation_date')
            if installation_date_str:
                try:
                    start_date = datetime.strptime(installation_date_str, "%Y-%m-%d").date()
                except ValueError:
                    start_date = today - timedelta(days=30)  # Fallback: 30 Tage
            else:
                start_date = today - timedelta(days=30)  # Fallback: 30 Tage
        elif isinstance(start_date, str):
            try:
                start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            except ValueError:
                start_date = today - timedelta(days=30)  # Fallback: 30 Tage
        
        total_days = (today - start_date).days + 1
        if total_days <= 0:
            return 0
        
        success_days = 0
        current_date = start_date
        
        # Zähle die Tage mit Lernerfolg
        while current_date <= today:
            date_str = current_date.strftime("%Y-%m-%d")
            stats = self.db.get_daily_stats(date_str, self.deck_id)
            
            cards_due = stats['cards_due']
            cards_studied = stats['cards_studied']
            
            if cards_due > 0 and cards_studied >= cards_due:
                success_days += 1
            
            current_date += timedelta(days=1)
        
        return (success_days / total_days) * 100


class StudyStatisticsCollector:
    """Klasse zum Sammeln von Lernstatistiken aus Anki"""
    
    def __init__(self, db):
        self.db = db
    
    def collect_daily_stats(self):
        """Sammelt die Lernstatistiken für den aktuellen Tag"""
        if not mw or not mw.col:
            print("Anki-Sammlung nicht verfügbar")
            return False
        
        today = datetime.now().strftime("%Y-%m-%d")
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_ms = int(today_start.timestamp() * 1000)
        today_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
        today_end_ms = int(today_end.timestamp() * 1000)
        
        try:
            decks = mw.col.decks.all()
            
            for deck in decks:
                deck_id = int(deck['id'])
                deck_name = deck['name']
                
                # Überspringe Standarddeck
                if deck_id == 1:
                    continue
                
                # Fällige Karten für den heutigen Tag
                try:
                    due_cards_query = f'deck:"{deck_name}" (is:new or is:due)'
                    due_cards = len(mw.col.find_cards(due_cards_query))
                except Exception as e:
                    print(f"Fehler beim Abrufen fälliger Karten für {deck_name}: {e}")
                    due_cards = 0
                
                # Gelernte Karten für den heutigen Tag
                try:
                    cards_studied = mw.col.db.scalar(f"""
                        SELECT COUNT(DISTINCT cid) 
                        FROM revlog r 
                        JOIN cards c ON r.cid = c.id 
                        WHERE c.did = {deck_id} 
                        AND r.id BETWEEN {today_start_ms} AND {today_end_ms}
                    """) or 0
                except Exception as e:
                    print(f"Fehler beim Abrufen gelernter Karten für {deck_name}: {e}")
                    cards_studied = 0
                
                # Lernzeit in Minuten
                try:
                    study_time = mw.col.db.scalar(f"""
                        SELECT CAST(COALESCE(SUM(time) / 60.0, 0) AS INTEGER)
                        FROM revlog r
                        JOIN cards c ON r.cid = c.id
                        WHERE c.did = {deck_id}
                        AND r.id BETWEEN {today_start_ms} AND {today_end_ms}
                    """) or 0
                except Exception as e:
                    print(f"Fehler beim Abrufen der Lernzeit für {deck_name}: {e}")
                    study_time = 0
                
                # Speichere die Statistiken
                self.db.save_daily_stats(today, deck_id, due_cards, cards_studied, study_time)
            
            return True
        except Exception as e:
            print(f"Fehler beim Sammeln der täglichen Statistiken: {e}")
            traceback.print_exc()
            return False
    
    def import_historical_revlog(self, days=90):
        """
        Importiert historische Reviewnamen aus dem Anki revlog mit Chunking für bessere Stabilität
        
        Args:
            days: Anzahl der Tage in die Vergangenheit (Standard: 90)
                
        Returns:
            bool: True bei Erfolg, False bei Fehler
        """
        if not mw or not mw.col:
            print("Anki-Sammlung nicht verfügbar")
            return False
        
        try:
            # Berechne Startdatum
            end_date = datetime.now().date()
            start_date = (end_date - timedelta(days=days))
            
            # Verwende Chunks für bessere Stabilität
            return self.import_historical_revlog_range(
                start_date.strftime("%Y-%m-%d"), 
                end_date.strftime("%Y-%m-%d")
            )
        except Exception as e:
            print(f"Fehler beim Import des historischen Reviewnamen: {e}")
            traceback.print_exc()
            return False

    def import_historical_revlog_range(self, start_date, end_date, chunk_size=30):
        """Importiert historische Daten in Chunks für bessere Stabilität"""
        if not mw or not mw.col:
            print("Anki-Sammlung nicht verfügbar")
            return False
            
        try:
            current_chunk_start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            
            # Hole alle Decks
            decks = mw.col.decks.all()
            overall_success = True
            
            while current_chunk_start <= end_date_obj:
                # Berechne Ende des aktuellen Chunks
                current_chunk_end = min(current_chunk_start + timedelta(days=chunk_size-1), end_date_obj)
                chunk_end_str = current_chunk_end.strftime("%Y-%m-%d")
                chunk_start_str = current_chunk_start.strftime("%Y-%m-%d")
                
                print(f"Study Tracker: Verarbeite Chunk {chunk_start_str} bis {chunk_end_str}...")
                
                try:
                    # Verarbeite jedes Deck in diesem Chunk
                    for deck in decks:
                        deck_id = int(deck['id'])
                        
                        # Überspringe Standarddeck
                        if deck_id == 1:
                            continue
                            
                        try:
                            self._process_revlog_chunk(deck_id, chunk_start_str, chunk_end_str)
                        except Exception as e:
                            print(f"Study Tracker: Fehler bei Deck {deck_id} im Chunk {chunk_start_str}-{chunk_end_str}: {e}")
                            overall_success = False
                except Exception as e:
                    # Fehler in einem Chunk stoppen nicht den gesamten Prozess
                    print(f"Study Tracker: Fehler im Chunk {chunk_start_str}-{chunk_end_str}: {e}")
                    traceback.print_exc()
                    overall_success = False
                
                # Nächster Chunk
                current_chunk_start = current_chunk_end + timedelta(days=1)
            
            # Aktualisiere das letzte Synchronisierungsdatum
            self.db.update_sync_date()
            
            return overall_success
        except Exception as e:
            print(f"Study Tracker: Fehler beim Import im Zeitraum: {e}")
            traceback.print_exc()
            return False
    def _process_revlog_chunk(self, deck_id, start_date, end_date):
        """Verarbeitet einen zeitlichen Chunk im Kontext einer Transaktion"""
        # Stelle sicher, dass keine Teiloperationen committet werden
        self.db.conn.execute("BEGIN TRANSACTION")
        
        try:
            # Erzeuge Liste aller Tage zwischen start_date und end_date
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            all_dates = []
            current_date = start_date_obj
            
            while current_date <= end_date_obj:
                all_dates.append(current_date.strftime("%Y-%m-%d"))
                current_date += timedelta(days=1)
            
            for date_str in all_dates:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                day_start_ms = int(datetime.combine(date_obj, datetime.min.time()).timestamp() * 1000)
                day_end_ms = int(datetime.combine(date_obj, datetime.max.time()).timestamp() * 1000)
                
                # Hole tatsächlich gelernte Karten für diesen Tag
                cards_studied = mw.col.db.scalar(f"""
                    SELECT COUNT(DISTINCT r.cid) 
                    FROM revlog r
                    JOIN cards c ON r.cid = c.id
                    WHERE c.did = {deck_id}
                    AND r.id BETWEEN {day_start_ms} AND {day_end_ms}
                """) or 0
                
                study_time = mw.col.db.scalar(f"""
                    SELECT CAST(SUM(r.time) / 60.0 AS INTEGER) 
                    FROM revlog r
                    JOIN cards c ON r.cid = c.id
                    WHERE c.did = {deck_id}
                    AND r.id BETWEEN {day_start_ms} AND {day_end_ms}
                """) or 0
                
                # Speichere gelernte Karten mit zugehörigen Metadaten
                card_data = mw.col.db.all(f"""
                    SELECT r.cid, r.time
                    FROM revlog r
                    JOIN cards c ON r.cid = c.id
                    WHERE c.did = {deck_id}
                    AND r.id BETWEEN {day_start_ms} AND {day_end_ms}
                """)
                
                for cid, review_time in card_data:
                    self.db.save_studied_card(date_str, cid, deck_id, review_time)
                
                # Skip if no cards were studied
                if cards_studied == 0:
                    continue
                
                # Schätze die fälligen Karten für diesen Tag
                # (Anki-Epochentage)
                anki_day = int(date_obj.timestamp() / 86400)
                
                # Hole die Anzahl der Karten, die an diesem Tag oder davor fällig waren
                cards_due = mw.col.db.scalar(f"""
                    SELECT COUNT(*)
                    FROM cards c
                    WHERE c.did = {deck_id}
                    AND c.queue IN (2, 3)
                    AND c.due <= {anki_day}
                """) or 0
                
                # Füge neue Karten hinzu, die für diesen Tag geplant waren
                new_cards_due = mw.col.db.scalar(f"""
                    SELECT COUNT(*)
                    FROM cards c
                    WHERE c.did = {deck_id}
                    AND c.queue = 0
                    AND c.due <= {anki_day}
                """) or 0
                
                cards_due += new_cards_due
                
                # Wenn cards_due < cards_studied, ist etwas falsch
                # (z.B. Karten wurden am selben Tag gelernt und erneut fällig)
                cards_due = max(cards_due, cards_studied)
                
                # Prüfe, ob bereits ein Eintrag existiert
                existing_stats = self.db.get_daily_stats(date_str, deck_id)
                existing_due = existing_stats['cards_due']
                existing_studied = existing_stats['cards_studied']
                existing_time = existing_stats['study_time']
                
                # Update nur, wenn neue Werte größer sind
                if cards_due > existing_due or cards_studied > existing_studied or study_time > existing_time:
                    self.db.save_daily_stats(
                        date_str,
                        deck_id,
                        max(existing_due, cards_due),
                        max(existing_studied, cards_studied),
                        max(existing_time, study_time)
                    )
            
            # Nur commit wenn alles erfolgreich war
            self.db.conn.commit()
            return True
        except Exception as e:
            # Bei Fehler Transaktion zurückrollen
            self.db.conn.rollback()
            print(f"Study Tracker: Transaktionsfehler: {e}")
            raise  # Rethrow für übergeordnete Fehlerbehandlung

    def process_validation_codes(self, note_id=None, specific_note=None):
        """
        Unified function to process validation codes from Anki cards.
        
        This function can either process a specific note (when provided) or scan all notes 
        with validation codes (when note_id and specific_note are None).
        
        Args:
            note_id: Optional, specific note ID to process
            specific_note: Optional, note object to process
            
        Returns:
            dict: Results summary with counts of processed notes and codes
        """
        if not mw or not mw.col:
            print("Study Tracker: Anki collection not available")
            return {"processed_notes": 0, "processed_codes": 0, "error": "Anki collection not available"}
        
        try:
            # Unified regex pattern for validation codes with various formats
            validation_pattern = r'(\d{4}[-\.]\d{2}[-\.]\d{2})(?:[:]\s*|\s+|:|-)(\d{4})'
            
            # Set to track unique codes to prevent duplicates
            processed_codes = set()
            processed_notes_count = 0
            processed_codes_count = 0
            
            # Determine which notes to process
            notes_to_process = []
            if specific_note:
                notes_to_process = [specific_note]
            elif note_id:
                try:
                    note = mw.col.get_note(note_id)
                    notes_to_process = [note]
                except Exception as e:
                    print(f"Study Tracker: Error retrieving note {note_id}: {e}")
                    return {"processed_notes": 0, "processed_codes": 0, "error": f"Error retrieving note: {e}"}
            else:
                # If no specific note, get all notes with ValidierungscodesListe field
                note_ids = mw.col.find_notes("ValidierungscodesListe:*")
                print(f"Study Tracker: Found: {len(note_ids)} notes with validation codes")
                
                for note_id in note_ids:
                    try:
                        note = mw.col.get_note(note_id)
                        notes_to_process.append(note)
                    except Exception as e:
                        print(f"Study Tracker: Error retrieving note {note_id}: {e}")
                        continue
            
            # Process each note
            for note in notes_to_process:
                try:
                    # Skip if no validation codes
                    if 'ValidierungscodesListe' not in note or not note['ValidierungscodesListe'].strip():
                        continue
                    
                    validation_content = note['ValidierungscodesListe'].strip()
                    chat_link = note['ChatGPT-Link'].strip() if 'ChatGPT-Link' in note else ''
                    
                    # Get all cards for this note
                    card_ids = note.card_ids()
                    if not card_ids:
                        continue
                    
                    # Debug info
                    print(f"Study Tracker: Processing note with {len(card_ids)} cards")
                    
                    # Process first card (validation codes apply to all cards in the note)
                    card_id = card_ids[0]
                    card = mw.col.get_card(card_id)
                    deck_id = card.did
                    card_id_str = str(card_id)
                    
                    # Get card title for better logs and database entries
                    card_title = ValidationCodeHandler(self.db).get_card_title(card_id_str)
                    
                    # Save ChatGPT link if available
                    if chat_link:
                        self.db.save_chat_link(card_id_str, chat_link, deck_id, card_title)
                        print(f"Study Tracker: ChatGPT-Link saved: {chat_link} for card {card_id_str}")
                    
                    # First, delete all existing validation codes for this card
                    try:
                        self.db.conn.execute("""
                            DELETE FROM validation_codes WHERE card_id = ?
                        """, (card_id_str,))
                        self.db.conn.commit()
                        print(f"Study Tracker: Removed existing validation codes for card {card_id_str}")
                    except Exception as e:
                        print(f"Study Tracker: Error removing existing validation codes: {e}")
                    
                    # Extract validation codes using regex
                    all_codes = re.findall(validation_pattern, validation_content)
                    
                    if not all_codes:
                        print(f"Study Tracker: No validation codes found in note")
                        continue
                    
                    print(f"Study Tracker: Found {len(all_codes)} validation codes")
                    
                    # Process each validation code
                    codes_found = 0
                    for date_str, code in all_codes:
                        # Normalize date format
                        date_str = date_str.replace('.', '-')
                        
                        # Create unique key to prevent duplicates
                        unique_key = f"{card_id_str}_{date_str}_{code}"
                        
                        if unique_key in processed_codes:
                            print(f"Study Tracker: Skipping duplicate: {date_str}: {code} for card {card_id_str}")
                            continue
                        
                        processed_codes.add(unique_key)
                        
                        # Parse code components
                        correct_percent = int(code[:2]) if len(code) >= 2 else 0
                        difficulty = int(code[2:4]) if len(code) >= 4 else 0
                        
                        # Insert validation code
                        try:
                            self.db.conn.execute("""
                                INSERT INTO validation_codes
                                (card_id, deck_id, date, code, correct_percent, difficulty, page_number, chat_link, card_title, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                card_id_str, 
                                deck_id, 
                                date_str, 
                                code, 
                                correct_percent,
                                difficulty,
                                0,  # page_number
                                chat_link, 
                                card_title,
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            ))
                            self.db.conn.commit()
                            
                            print(f"Study Tracker: Validation code saved: {date_str}: {code}")
                            codes_found += 1
                            processed_codes_count += 1
                        except Exception as e:
                            print(f"Study Tracker: Error saving validation code {date_str}: {code}: {e}")
                            continue
                    
                    if codes_found > 0:
                        print(f"Study Tracker: {codes_found} validation codes for card {card_id_str} found and saved")
                    
                    processed_notes_count += 1
                    
                except Exception as e:
                    print(f"Study Tracker: Error processing note: {e}")
                    traceback.print_exc()
                    continue
            
            # Commit all changes
            self.db.conn.commit()
            
            print(f"Study Tracker: Validation code import completed: {processed_codes_count} codes from {processed_notes_count} notes")
            
            return {
                "processed_notes": processed_notes_count,
                "processed_codes": processed_codes_count
            }
        except Exception as e:
            print(f"Study Tracker: Error processing validation codes: {e}")
            traceback.print_exc()
            return {
                "processed_notes": 0, 
                "processed_codes": 0,
                "error": str(e)
            }
    
    def parse_validation_codes_from_cards(self):
        """
        Scans all cards for ValidierungscodesListe field and imports the codes 
        into the database using the unified function.
        
        Returns:
            bool: True on success, False on error
        """
        try:
            print("Study Tracker: Importing validation codes from cards...")
            result = self.process_validation_codes()
            
            # Process results
            processed_notes = result.get("processed_notes", 0)
            processed_codes = result.get("processed_codes", 0)
            error = result.get("error")
            
            if error:
                print(f"Study Tracker: Error during validation code import: {error}")
                return False
                
            print(f"Study Tracker: Validation code import completed: {processed_codes} codes from {processed_notes} notes")
            return True
        except Exception as e:
            print(f"Study Tracker: Error parsing validation codes: {e}")
            traceback.print_exc()
            return False
    
    def link_chat_links_with_validation_codes(self):
        """
        Links existing ChatGPT links with validation codes for cards
        where the link is missing, with improved error handling
        
        Returns:
            bool: True on success, False on error
        """
        try:
            print("Study Tracker: Linking ChatGPT links with validation codes...")
            
            # Find validation codes without ChatGPT links
            cursor = self.db.conn.execute("""
                SELECT v.id, v.card_id, c.link
                FROM validation_codes v
                JOIN chat_links c ON v.card_id = c.card_id
                WHERE (v.chat_link IS NULL OR v.chat_link = '')
                AND c.link IS NOT NULL
            """)
            
            updates = cursor.fetchall()
            
            if not updates:
                print("Study Tracker: No validation codes without linked ChatGPT links found.")
                return True
            
            print(f"Study Tracker: Found: {len(updates)} validation codes without linked ChatGPT links")
            
            updated_count = 0
            
            # Update validation codes with their associated ChatGPT links
            for validation_id, card_id, chat_link in updates:
                try:
                    self.db.conn.execute("""
                        UPDATE validation_codes
                        SET chat_link = ?
                        WHERE id = ?
                    """, (chat_link, validation_id))
                    
                    updated_count += 1
                    print(f"Study Tracker: Validation code {validation_id} for card {card_id} linked with ChatGPT link.")
                except Exception as e:
                    print(f"Study Tracker: Error updating validation code {validation_id}: {e}")
            
            # Commit the changes
            self.db.conn.commit()
            
            print(f"Study Tracker: Total {updated_count} validation codes linked with ChatGPT links.")
            
            return True
        except Exception as e:
            print(f"Study Tracker: Error linking ChatGPT links: {e}")
            traceback.print_exc()
            return False
    
    def initialize_level_system(self, deck_id=None):
        """
        Initialisiert oder aktualisiert das Level-System für ein bestimmtes Deck
        oder für alle Decks wenn deck_id=None
        """
        try:
            print(f"Study Tracker: Initialisiere Level-System für Deck {deck_id if deck_id is not None else 'Alle'}")
            
            # Wenn kein Deck angegeben, alle aktiven Decks durchgehen
            if deck_id is None:
                if not mw or not mw.col:
                    print("Study Tracker: Anki-Sammlung nicht verfügbar")
                    return False
                    
                decks = mw.col.decks.all()
                for deck in decks:
                    # Überspringe Standard-Deck
                    if deck['id'] == 1:
                        continue
                        
                    self.initialize_level_system(deck['id'])
                
                return True
            
            # Konvertiere deck_id zu Integer für konsistente Handhabung
            deck_id_int = int(deck_id) if deck_id is not None else None
            
            # Prüfe, ob bereits ein Level-Eintrag für dieses Deck existiert
            level_data = self.db.get_level_progress(deck_id_int)
            
            if not level_data:
                # Erstelle einen neuen Level-Eintrag
                start_date = datetime.now().date()
                level = 1 # Starte mit Level 1
                
                success = self.db.save_level_progress(deck_id_int, level, start_date)
                
                if success:
                    print(f"Study Tracker: Neues Level-System für Deck {deck_id_int} initialisiert (Level {level})")
                    
                    # Erstelle einen ersten Level-Change-Eintrag
                    self.db.save_level_change(deck_id_int, "init", 0, level)
                else:
                    print(f"Study Tracker: Fehler beim Initialisieren des Level-Systems für Deck {deck_id_int}")
            else:
                # NEU: Prüfe wie alt der bestehende Abschnitt ist
                today = datetime.now().date()
                period_start = level_data['start_date']
                days_since_start = (today - period_start).days
                
                # Prüfe, ob kürzlich ein neuer Abschnitt gestartet wurde
                three_days_ago = today - timedelta(days=3)
                cursor = self.db.conn.execute("""
                    SELECT COUNT(*) FROM level_history
                    WHERE deck_id = ? AND date(change_date) >= ? 
                    AND change_type IN ('new_period', 'reset_period', 'early_completion', 'init')
                """, (deck_id_int, three_days_ago.strftime("%Y-%m-%d")))
                
                recent_changes = cursor.fetchone()[0]
                
                # Führe Periodencheck nur durch, wenn das Startdatum älter als 3 Tage ist
                # und es keine kürzlichen Änderungen gab
                if days_since_start > 3 and recent_changes == 0:
                    level_system = LevelSystem(self.db, deck_id_int)
                    
                    # Prüfe die Abschnittsergebnisse
                    result = level_system.check_period_completion()
                    
                    if result:
                        print(f"Study Tracker: Level-System für Deck {deck_id_int} aktualisiert: {result}")
                else:
                    print(f"Study Tracker: Abschnitt für Deck {deck_id_int} ist erst {days_since_start} Tage alt oder wurde kürzlich aktualisiert. Überspringe Prüfung.")
            
            return True
        except Exception as e:
            print(f"Study Tracker: Fehler bei der Initialisierung des Level-Systems: {e}")
            traceback.print_exc()
            return False

    def parse_validation_code(self, code):
        """
        Improved version of parse_validation_codes_from_cards that prevents duplicates
        and handles validation codes more robustly.
        """
        if not mw or not mw.col:
            print("Study Tracker: Anki collection not available")
            return False
        
        try:
            # Improved regex for validation codes with multiple formats
            validation_pattern = r'(\d{4}[-\.]\d{2}[-\.]\d{2})(?:[:]\s*|\s+|:|-)(\d{4})'
            
            # Get all notes with ValidationCodesListe field
            note_ids = mw.col.find_notes("ValidierungscodesListe:*")
            
            print(f"Study Tracker: Found: {len(note_ids)} notes with validation codes")
            
            # Add a set to track already processed combinations to avoid duplicates
            processed_codes = set()
            
            # Count for summary
            processed_notes = 0
            processed_codes_count = 0
            
            for note_id in note_ids:
                try:
                    note = mw.col.get_note(note_id)
                    
                    # Check if the required field exists
                    if 'ValidierungscodesListe' not in note or not note['ValidierungscodesListe'].strip():
                        continue
                        
                    # Extract validation code content
                    validation_content = note['ValidierungscodesListe'].strip()
                    
                    # Get associated ChatGPT link
                    chat_link = note['ChatGPT-Link'].strip() if 'ChatGPT-Link' in note else ''
                    
                    # Get all cards of this note
                    card_ids = note.card_ids()
                    if not card_ids:
                        continue
                        
                    # Debug for this note
                    print(f"Study Tracker: Processing note {note_id} with {len(card_ids)} cards")
                    print(f"Study Tracker: Validation codes: {validation_content}")
                    
                    # Find all validation codes
                    all_codes = re.findall(validation_pattern, validation_content)
                    
                    if not all_codes:
                        continue
                    
                    # Process first card of the note (all cards share the same content)
                    card_id = card_ids[0]
                    card = mw.col.get_card(card_id)
                    deck_id = card.did
                    
                    # Convert card_id to string for consistent handling
                    card_id_str = str(card_id)
                    
                    # Get card title
                    handler = ValidationCodeHandler(self.db)
                    card_title = handler.get_card_title(card_id_str)
                
                    # Save ChatGPT link if present
                    if chat_link:
                        self.db.save_chat_link(card_id_str, chat_link, deck_id, card_title)
                        print(f"Study Tracker: ChatGPT link saved: {chat_link} for card {card_id_str}")
                    
                    # Process each validation code
                    codes_found = 0
                    for date_str, code in all_codes:
                        # Normalize date format to YYYY-MM-DD
                        date_str = date_str.replace('.', '-')
                        
                        # Create a unique key for this code
                        unique_key = f"{card_id_str}_{date_str}_{code}"
                        
                        # Skip if already processed
                        if unique_key in processed_codes:
                            print(f"Study Tracker: Skipping duplicate code: {date_str}: {code} for card {card_id_str}")
                            continue
                        
                        print(f"Study Tracker: Validation code found: {date_str}: {code}")
                        
                        # Check if this exact code already exists in the database
                        cursor = self.db.conn.execute("""
                            SELECT COUNT(*) FROM validation_codes
                            WHERE card_id = ? AND date = ? AND code = ?
                        """, (card_id_str, date_str, code))
                        
                        if cursor.fetchone()[0] > 0:
                            print(f"Study Tracker: Code already exists in database: {date_str}: {code}")
                            processed_codes.add(unique_key)
                            continue
                        
                        # Extract correctness and difficulty
                        correct_percent = int(code[:2]) if len(code) >= 2 else 0
                        difficulty = int(code[2:4]) if len(code) >= 4 else 0
                        
                        # Save code to database
                        try:
                            self.db.conn.execute("""
                                INSERT INTO validation_codes
                                (card_id, deck_id, date, code, correct_percent, difficulty, page_number, chat_link, card_title, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                card_id_str, 
                                deck_id, 
                                date_str,
                                code, 
                                correct_percent,
                                difficulty,
                                0,  # page_number
                                chat_link, 
                                card_title,
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            ))
                            self.db.conn.commit()
                            
                            processed_codes.add(unique_key)
                            codes_found += 1
                            processed_codes_count += 1
                            print(f"Study Tracker: Validation code saved: {date_str}: {code}")
                        except Exception as e:
                            print(f"Study Tracker: Error saving validation code {date_str}: {code}: {e}")
                            continue
                    
                    if codes_found > 0:
                        print(f"Study Tracker: {codes_found} validation codes found and saved for card {card_id_str}")
                    
                    processed_notes += 1
                    
                except Exception as e:
                    print(f"Study Tracker: Error processing note {note_id}: {e}")
                    traceback.print_exc()
                    continue
            
            # Commit changes
            self.db.conn.commit()
            
            print(f"Study Tracker: Validation code import completed: {processed_codes_count} codes from {processed_notes} notes")
            
            return True
        except Exception as e:
            print(f"Study Tracker: Error parsing validation codes: {e}")
            traceback.print_exc()
            return False

class CachedReportData:
    """Caching-Klasse für Berichtsdaten"""
    def __init__(self):
        self.cache = {}
        self.max_age = 300  # 5 Minuten Cache-Lebensdauer
    
    def get(self, key):
        """Holt gecachte Daten, falls vorhanden und nicht zu alt"""
        if key in self.cache:
            timestamp, data = self.cache[key]
            if time.time() - timestamp < self.max_age:
                return data
        return None
    
    def set(self, key, data):
        """Speichert Daten im Cache"""
        self.cache[key] = (time.time(), data)
        
    def invalidate(self, key=None):
        """Entfernt spezifische oder alle Cache-Einträge"""
        if key:
            if key in self.cache:
                del self.cache[key]
        else:
            self.cache.clear()

class ReportGenerator:
    """Verbesserte Klasse zur Generierung von HTML-Berichten mit robuster Datenanbindung"""
    
    def __init__(self, db):
        self.db = db

    def extract_validation_data_for_report(self, deck_id, start_date, end_date):
        """
        Extrahiert und bereitet Validierungscodes für den Bericht mit 
        optimierten SQL-Abfragen für bessere Zuverlässigkeit
        
        Args:
            deck_id: ID des Decks
            start_date: Startdatum im Format YYYY-MM-DD
            end_date: Enddatum im Format YYYY-MM-DD
                
        Returns:
            list: Liste von aufbereiteten Validierungscode-Dictionaries
        """
        try:
            print(f"Study Tracker: Extrahiere Validierungscodes für Deck {deck_id}, Zeitraum {start_date} bis {end_date}")
            
            # Verwende eine UNION-Abfrage, um alle Information in einer Abfrage zu holen
            query = """
            SELECT 
                v.date, 
                v.code, 
                v.correct_percent, 
                v.difficulty, 
                v.page_number, 
                COALESCE(v.chat_link, c.link) as chat_link, 
                v.card_id, 
                COALESCE(v.card_title, c.card_title, 'Unbekannte Karte') as card_title
            FROM validation_codes v
            LEFT JOIN chat_links c ON v.card_id = c.card_id
            WHERE v.deck_id = ? AND v.date BETWEEN ? AND ?
            
            UNION
            
            -- Hole alle ChatGPT-Links, selbst wenn kein Validierungscode existiert
            SELECT 
                NULL as date, 
                NULL as code, 
                NULL as correct_percent,
                NULL as difficulty,
                NULL as page_number,
                c.link as chat_link,
                c.card_id,
                c.card_title
            FROM chat_links c
            WHERE c.deck_id = ? 
            AND c.card_id NOT IN (
                SELECT card_id FROM validation_codes 
                WHERE deck_id = ? AND date BETWEEN ? AND ?
            )
            ORDER BY date
            """
            
            # Führe die Abfrage mit allen notwendigen Parametern aus
            params = (deck_id, start_date, end_date, deck_id, deck_id, start_date, end_date)
            
            # Verwende Timeout für lange Abfragen
            cursor = self.execute_with_timeout(self.db.conn, query, params)
            results = cursor.fetchall()
            
            print(f"Study Tracker: Gefunden: {len(results)} Validierungscodes für Bericht (SQL)")
            
            # Verarbeite die Daten in das erwartete Format
            validation_data = []
            
            for result in results:
                try:
                    if len(result) >= 8:
                        date, code, correct_percent, difficulty, page_number, chat_link, card_id, card_title = result
                        
                        # Überspringen wenn Karteninhalt nicht relevant ist
                        if not date and not code and not chat_link:
                            continue
                        
                        # Wenn card_title fehlt, versuche ihn zu ermitteln
                        if not card_title:
                            card_title = ValidationCodeHandler(self.db).get_card_title(card_id)
                            if not card_title:
                                card_title = "Unbekannte Karte"
                        
                        # Parse Code-Komponenten wenn nötig
                        if code and (correct_percent is None or difficulty is None):
                            parsed = ValidationCodeHandler(self.db).parse_code(code)
                            correct_percent = parsed['correct_percent'] if correct_percent is None else correct_percent
                            difficulty = parsed['difficulty'] if difficulty is None else difficulty
                        
                        validation_data.append({
                            'date': date,
                            'validationCode': code,
                            'correctPercent': correct_percent,
                            'difficulty': difficulty,
                            'pageNumber': page_number or 0,
                            'chatLink': chat_link,
                            'cardId': str(card_id),
                            'cardTitle': card_title
                        })
                        
                except Exception as e:
                    print(f"Study Tracker: Fehler bei Verarbeitung eines Validierungscodes: {e}")
                    continue
            
            # Wenn keine Daten gefunden wurden, versuche eine alternative Abfrage
            if not validation_data:
                print("Study Tracker: Keine Validierungscodes gefunden, versuche alternative Abfrage...")
                validation_data = self._fallback_extract_validation_data(deck_id, start_date, end_date)
            
            return validation_data
        except Exception as e:
            print(f"Study Tracker: Fehler beim Extrahieren der Validierungsdaten: {e}")
            traceback.print_exc()
            # Fallback zur ursprünglichen Abfrage
            return self._fallback_extract_validation_data(deck_id, start_date, end_date)
        
    def _fallback_extract_validation_data(self, deck_id, start_date, end_date):
        """Fallback-Methode zur Extraktion von Validierungscodes mit einfacheren Abfragen"""
        try:
            print("Study Tracker: Verwende Fallback-Methode für Validierungscodes...")
            validation_data = []
            
            # Einfachere Abfrage für Validierungscodes
            cursor = self.db.conn.execute("""
                SELECT date, code, card_id, card_title, chat_link
                FROM validation_codes
                WHERE date BETWEEN ? AND ?
            """, (start_date, end_date))
            
            results = cursor.fetchall()
            print(f"Study Tracker: Alternative Abfrage fand {len(results)} Validierungscodes")
            
            for result in results:
                try:
                    if len(result) >= 3:
                        date, code, card_id = result[:3]
                        card_title = result[3] if len(result) > 3 and result[3] else "Unbekannte Karte"
                        chat_link = result[4] if len(result) > 4 and result[4] else None
                        
                        # Prüfe, ob die Karte zum ausgewählten Deck gehört
                        if mw and mw.col:
                            try:
                                card = mw.col.get_card(int(card_id))
                                if card and card.did != deck_id:
                                    continue  # Überspringe Karten aus anderen Decks
                            except:
                                pass  # Wenn Karte nicht gefunden, trotzdem einbeziehen
                        
                        # Parse den Code
                        correct_percent = int(code[:2]) if len(code) >= 2 else 0
                        difficulty = int(code[2:4]) if len(code) >= 4 else 0
                        
                        validation_data.append({
                            'date': date,
                            'validationCode': code,
                            'correctPercent': correct_percent,
                            'difficulty': difficulty,
                            'pageNumber': 0,
                            'chatLink': chat_link,
                            'cardId': str(card_id),
                            'cardTitle': card_title
                        })
                except Exception as e:
                    print(f"Study Tracker: Fehler bei Fallback-Verarbeitung: {e}")
                    continue
                    
            return validation_data
        except Exception as e:
            print(f"Study Tracker: Fehler bei Fallback-Extraktion: {e}")
            return []

    def execute_with_timeout(self, connection, query, params, timeout=30):
        """Führt eine SQL-Abfrage mit Timeout aus"""
        # In SQLite-Version ≥3.8.0
        original_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        
        try:
            # Setze Timeout (in Millisekunden)
            connection.execute(f"PRAGMA busy_timeout = {timeout * 1000}")
            return connection.execute(query, params)
        finally:
            # Stelle ursprünglichen Timeout wieder her
            connection.execute(f"PRAGMA busy_timeout = {original_timeout}")

    def generate_report(self, deck_id, start_date, end_date):
        """
        Generiert einen vollständigen HTML-Bericht für den angegebenen Zeitraum
        mit verbesserter Datenabfrage und Verarbeitung
        
        Args:
            deck_id: ID des Decks
            start_date: Startdatum im Format YYYY-MM-DD
            end_date: Enddatum im Format YYYY-MM-DD
            
        Returns:
            str: HTML-Inhalt des Berichts
        """
        # Bereinige doppelte Level-Einträge vor der Berichterstellung
        self.db.clean_duplicate_level_entries()
        
        try:
            # Hole Deckname
            deck_name = "Unbekannter Stapel"
            if mw and mw.col:
                try:
                    deck = mw.col.decks.get(deck_id)
                    if deck:
                        deck_name = deck['name']
                except Exception as e:
                    print(f"Study Tracker: Fehler beim Abrufen des Decknamens: {e}")
            
            # NEU: Aktualisiere Validierungscodes und ChatGPT-Links vor der Berichterstellung
            try:
                print("Study Tracker: Aktualisiere Validierungscodes und ChatGPT-Links vor Berichtserstellung...")
                collector = StudyStatisticsCollector(self.db)
                collector.parse_validation_codes_from_cards()
                print("Study Tracker: Aktualisierung abgeschlossen")
            except Exception as e:
                print(f"Study Tracker: Fehler bei der Aktualisierung vor Berichtserstellung: {e}")
                traceback.print_exc()
            
            # VERBESSERT: Extrahiere Validierungsdaten mit direkter SQL-Abfrage
            validation_data = self.extract_validation_data_for_report(deck_id, start_date, end_date)
            
            # Sammel alle verfügbaren Karten im Zeitraum (aus studied_cards)
            all_studied_card_ids = set()
            
            # Durchsuche den Zeitraum nach gelernten Karten
            current_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            
            while current_date <= end_date_obj:
                date_str = current_date.strftime("%Y-%m-%d")
                # Hole gelernte Karten für diesen Tag
                studied_cards = self.db.get_studied_cards(date_str, deck_id)
                for card_data in studied_cards:
                    if len(card_data) > 0:  # Stelle sicher, dass Daten vorhanden sind
                        card_id = str(card_data[0])  # Konsistente ID-Behandlung
                        all_studied_card_ids.add(card_id)
                
                current_date += timedelta(days=1)
            
            print(f"Study Tracker: Insgesamt {len(all_studied_card_ids)} gelernte Karten im Zeitraum gefunden")
            
            # NEU: Direkte Abfrage aller ChatGPT-Links für das Deck
            chat_links = {}
            try:
                cursor = self.db.conn.execute("""
                    SELECT card_id, link FROM chat_links
                    WHERE deck_id = ?
                """, (deck_id,))
                
                for card_id, link in cursor.fetchall():
                    chat_links[str(card_id)] = link
                
                print(f"Study Tracker: Direkt abgefragt: {len(chat_links)} ChatGPT-Links")
            except Exception as e:
                print(f"Study Tracker: Fehler bei direkter ChatGPT-Link-Abfrage: {e}")
            
            # Konvertiere in JSON-Format für JavaScript
            validation_data_json = json.dumps(validation_data)

            # Debug-Ausgabe, um die Daten zu überprüfen
            print(f"Level history raw data: {level_history[:2] if level_history else 'None'}")

            
            # VERBESSERT: Hole gelernte Karten pro Tag mit direkter SQL-Abfrage für Details
            day_details = {}
            
            try:
                current_date = datetime.strptime(start_date, "%Y-%m-%d").date()
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
                
                # Für jeden Tag im Zeitraum
                while current_date <= end_date_obj:
                    date_str = current_date.strftime("%Y-%m-%d")
                    
                    # NEU: Direkte SQL-Abfrage für alle gelernten Karten dieses Tages mit Details
                    cursor = self.db.conn.execute("""
                        SELECT 
                            s.card_id, 
                            s.deck_id, 
                            s.review_time, 
                            c.link as chat_link,
                            (SELECT card_title FROM validation_codes WHERE card_id = s.card_id LIMIT 1) as card_title
                        FROM studied_cards s
                        LEFT JOIN chat_links c ON s.card_id = c.card_id
                        WHERE s.date = ? AND s.deck_id = ?
                    """, (date_str, deck_id))
                    
                    day_cards = cursor.fetchall()
                    
                    cards_info = []
                    for card_data in day_cards:
                        try:
                            card_id = str(card_data[0])
                            studied_deck_id = card_data[1]
                            review_time = card_data[2]
                            chat_link = card_data[3]
                            card_title = card_data[4]
                            
                            # Wenn Titel fehlt, versuche ihn zu ermitteln
                            if not card_title:
                                card_title = ValidationCodeHandler(self.db).get_card_title(card_id)
                                
                                # Fallback: Versuche Titel aus der Anki-Datenbank zu holen
                                if not card_title and mw and mw.col:
                                    try:
                                        card = mw.col.get_card(int(card_id))
                                        if card:
                                            note = card.note()
                                            if 'Vorderseite' in note:
                                                card_title = note['Vorderseite']
                                            elif 'Front' in note:
                                                card_title = note['Front']
                                            elif note.keys():
                                                card_title = note[note.keys()[0]]
                                    except Exception as e:
                                        print(f"Study Tracker: Fehler beim Laden des Kartentitels aus Anki: {e}")
                                
                                if not card_title:
                                    card_title = "Karte " + card_id
                            
                            # Finde ChatGPT-Link, wenn nicht vorhanden
                            if not chat_link:
                                chat_link = chat_links.get(card_id)
                            
                            # Finde zugehörige Validierungscodes für die Karte
                            card_validation_codes = [v for v in validation_data if str(v['cardId']) == card_id]
                            
                            # Mehr Debug-Informationen
                            if card_validation_codes:
                                print(f"Study Tracker: Für Karte {card_id} ({card_title}) gefunden: {len(card_validation_codes)} Validierungscodes")
                            else:
                                print(f"Study Tracker: Für Karte {card_id} ({card_title}) KEINE Validierungscodes gefunden")
                                
                                # NEU: Direkter Versuch, Validierungscodes für diese Karte zu finden
                                direct_codes = self.db.get_validation_codes_for_card(card_id)
                                if direct_codes and len(direct_codes) > 0:
                                    print(f"Study Tracker: Direkt gefunden: {len(direct_codes)} Codes für Karte {card_id}")
                                    
                                    # Transformiere die direkt gefundenen Codes in das richtige Format
                                    for dc in direct_codes:
                                        if len(dc) >= 2:
                                            date, code_str = dc[0], dc[1]
                                            correct_percent = int(code_str[:2]) if len(code_str) >= 2 else 0
                                            difficulty = int(code_str[2:4]) if len(code_str) >= 4 else 0
                                            
                                            card_validation_codes.append({
                                                'date': date,
                                                'validationCode': code_str,
                                                'correctPercent': correct_percent,
                                                'difficulty': difficulty,
                                                'cardId': card_id,
                                                'cardTitle': card_title
                                            })
                            
                            cards_info.append({
                                "card_id": card_id,
                                "card_title": card_title,
                                "time_spent": review_time,
                                "chat_link": chat_link,
                                "validation_codes": card_validation_codes
                            })
                        except Exception as e:
                            print(f"Study Tracker: Fehler beim Verarbeiten der Kartendetails: {e}")
                            continue
                    
                    if cards_info:
                        day_details[date_str] = cards_info
                    
                    current_date += timedelta(days=1)
                
                print(f"Study Tracker: Kartendetails für {len(day_details)} Tage gesammelt")
                
            except Exception as e:
                print(f"Study Tracker: Fehler beim Sammeln der Tagesdetails: {e}")
                traceback.print_exc()
            
            # Erzeuge den HTML-Bericht
            html_content = self._generate_html_report(
                deck_name,
                validation_data_json,
                level_history_json,
                day_details,
                start_date,
                end_date,
                deck_id
            )
            
            return html_content
        except Exception as e:
            print(f"Study Tracker: Fehler bei der Berichtsgenerierung: {e}")
            traceback.print_exc()
            
            # Erstelle minimalen Fehlerbericht
            error_html = f"""<!DOCTYPE html>
            <html>
            <head><title>Fehler bei der Berichtsgenerierung</title></head>
            <body>
                <h1>Fehler bei der Berichtsgenerierung</h1>
                <p>Es ist ein Fehler aufgetreten: {str(e)}</p>
                <p>Bitte überprüfen Sie die Anki-Konsole für weitere Details.</p>
            </body>
            </html>"""
            return error_html


    
    def get_card_validation_codes(self, validation_data, card_id):
        """Extrahiert Validierungscodes für eine bestimmte Karte aus den validierten Daten"""
        if not card_id:
            return []
        
        card_codes = []
        for code_data in validation_data:
            if str(code_data.get('cardId', '')) == str(card_id):
                card_codes.append(code_data)
        
        return card_codes

    def get_level_history_direct(self, deck_id, start_date, end_date):
        """
        Fragt die Level-Historie direkt aus der Datenbank ab, ohne Umwandlung in JSON
        Verbesserte Version mit detaillierter Fehlerbehandlung und Debug-Ausgaben
        """
        try:
            print(f"Study Tracker: Direct DB Query - Hole Level-Historie für Deck {deck_id}")
            print(f"  - Zeitraum: {start_date} bis {end_date}")
            
            # Sicherstellen, dass deck_id ein Integer ist
            if deck_id is not None:
                try:
                    deck_id_int = int(deck_id)
                except (ValueError, TypeError):
                    print(f"Study Tracker: Konnte deck_id '{deck_id}' nicht zu Integer konvertieren")
                    deck_id_int = deck_id
            else:
                deck_id_int = None
            
            # SQL-Abfrage mit Parametern für das angegebene Deck und den Zeitraum
            query = """
                SELECT change_date, change_type, old_level, new_level
                FROM level_history
                WHERE deck_id = ? AND date(change_date) BETWEEN date(?) AND date(?)
                ORDER BY change_date ASC
            """
            
            # Ausgabe der Parameter zur Diagnose
            print(f"  - SQL-Parameter: deck_id={deck_id_int}, start_date={start_date}, end_date={end_date}")
            
            # Führe die Abfrage aus
            cursor = self.db.conn.execute(query, (deck_id_int, start_date, end_date))
            results = cursor.fetchall()
            
            print(f"Study Tracker: Direkte Abfrage ergab {len(results)} Level-Änderungen")
            
            # Wandle die Tupel in eine Liste von Dictionaries um
            level_changes = []
            for row in results:
                if len(row) >= 4:
                    change_date, change_type, old_level, new_level = row
                    
                    # Debug-Ausgabe
                    print(f"Study Tracker: Level-Änderung: {change_date}, {change_type}, {old_level} -> {new_level}")
                    
                    # Formatiere das Datum
                    formatted_date = change_date
                    try:
                        date_obj = datetime.strptime(change_date, "%Y-%m-%d %H:%M:%S").date()
                        formatted_date = format_date(date_obj)
                    except ValueError:
                        try:
                            date_obj = datetime.strptime(change_date, "%Y-%m-%d").date()
                            formatted_date = format_date(date_obj)
                        except ValueError:
                            # Belasse das Datum wie es ist
                            pass
                    
                    level_changes.append({
                        'date': change_date,
                        'formatted_date': formatted_date,
                        'change_type': change_type,
                        'old_level': old_level,
                        'new_level': new_level
                    })
            
            return level_changes
        except Exception as e:
            print(f"Study Tracker: Fehler bei direkter Level-Historie-Abfrage: {e}")
            traceback.print_exc()
            return []
    
    def _generate_html_report(self, deck_name, validation_data_json, level_history_json, day_details, start_date, end_date, deck_id):
        """Generiert den eigentlichen HTML-Bericht mit tabellarischer Darstellung statt Diagrammen"""
        # Debugging: Überprüfe das Level-History-JSON
        print("\n===== LEVEL HISTORY DEBUG IN _generate_html_report =====")
        print(f"Level history JSON Typ: {type(level_history_json)}")
        print(f"Level history JSON Inhalt (gekürzt): {level_history_json[:200]}")
        try:
            # Parse JSON zurück zu Python-Objekten
            parsed_level_data = json.loads(level_history_json)
            print(f"Parsed level data Typ: {type(parsed_level_data)}")
            print(f"Parsed level data Länge: {len(parsed_level_data)}")
            if parsed_level_data:
                print(f"Erstes Element: {parsed_level_data[0]}")
        except Exception as e:
            print(f"Fehler beim Parsen des JSON: {e}")
            parsed_level_data = []
        print("===== END DEBUG =====\n")

        # Parse JSON data back to Python objects
        try:
            level_history_data = json.loads(level_history_json)
            print(f"Successfully parsed level_history_json: {level_history_data[:2]}")
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Error parsing level_history_json: {e}")
            level_history_data = []
            
        try:
            validation_data = json.loads(validation_data_json)
        except (json.JSONDecodeError, TypeError):
            validation_data = []

        # Berechne tägliche Statistiken für den Zeitraum
        daily_stats = {}
        current_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        while current_date <= end_date_obj:
            date_str = current_date.strftime("%Y-%m-%d")
            stats = self.db.get_daily_stats(date_str, deck_id)
            cards_due = stats['cards_due']
            cards_studied = stats['cards_studied']
            
            daily_stats[date_str] = {
                'cards_due': cards_due,
                'cards_studied': cards_studied,
                'success': cards_due > 0 and cards_studied >= cards_due
            }
            
            current_date += timedelta(days=1)
        
        # Berechne zusammenfassende Statistiken
        total_days = len(daily_stats)
        total_studied_cards = sum(stats['cards_studied'] for stats in daily_stats.values())
        total_due_cards = sum(stats['cards_due'] for stats in daily_stats.values())
        successful_days = sum(1 for stats in daily_stats.values() if stats['success'])
        
        learning_days = sum(1 for stats in daily_stats.values() if stats['cards_studied'] > 0)
        avg_cards_per_day = total_studied_cards / learning_days if learning_days > 0 else 0
        success_rate = (successful_days / total_days) * 100 if total_days > 0 else 0
        
        # Define CSS separately to avoid f-string issues
        css = """
        /* Ausklappbare Zeilen */
        .expandable-row {
            display: none;
        }
        
        .expandable-content {
            padding: 16px;
            background-color: #f9fafb;
            border-radius: 6px;
            box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.1);
            margin: 8px;
        }
        
        /* Tageszeilen */
        .expand-trigger {
            cursor: pointer;
            transition: background-color 0.2s;
        }
        
        .expand-trigger:hover {
            background-color: #f3f4f6;
        }
        
        /* Kartenzeilen */
        .card-row {
            cursor: pointer;
            transition: background-color 0.2s;
        }
        
        .card-row:hover {
            background-color: #eff6ff;
        }
        
        /* Kompetenzansicht */
        .competency-view {
            background-color: #eff6ff;
            border: 1px solid #bfdbfe;
            border-radius: 6px;
            padding: 16px;
            margin: 12px 0;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
            transition: all 0.3s ease;
        }
        
        .competency-view.hidden {
            display: none;
        }
        
        /* Schließen-Button */
        .close-competency-view {
            cursor: pointer;
            transition: background-color 0.2s;
        }
        
        .close-competency-view:hover {
            background-color: #e5e7eb;
        }
        
        /* Tabellenstile */
        .card-list-container table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            border-radius: 6px;
            overflow: hidden;
            border: 1px solid #e5e7eb;
        }
        
        .card-list-container th {
            background-color: #f9fafb;
            font-weight: 600;
            padding: 10px 16px;
            text-align: left;
        }
        
        .card-list-container td {
            padding: 10px 16px;
            border-top: 1px solid #e5e7eb;
        }
        
        /* Validierungscode-Tabelle */
        .validation-code-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            margin-top: 10px;
            border: 1px solid #e5e7eb;
            border-radius: 4px;
            overflow: hidden;
        }
        
        .validation-code-table th {
            background-color: #f0f9ff;
            font-weight: 600;
            padding: 8px 12px;
            text-align: left;
        }
        
        .validation-code-table td {
            padding: 8px 12px;
            border-top: 1px solid #e5e7eb;
        }
        
        /* Level-Historie Tabelle */
        .level-history-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            margin-top: 10px;
            border: 1px solid #e5e7eb;
            border-radius: 4px;
            overflow: hidden;
        }
        
        .level-history-table th {
            background-color: #f0f5ff;
            font-weight: 600;
            padding: 8px 12px;
            text-align: left;
        }
        
        .level-history-table td {
            padding: 8px 12px;
            border-top: 1px solid #e5e7eb;
        }
        """
        
        # HTML generieren
        html = f"""<!DOCTYPE html>
    <html lang="de">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Lernbericht: {escape_html(deck_name)}</title>
        
        <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
        
        <style>
        {css}
        </style>
    </head>
    <body class="bg-gray-50 text-gray-900">
        <div class="container mx-auto px-4 py-8">
            <header class="mb-8">
                <h1 class="text-3xl font-bold mb-2">Lernbericht: {escape_html(deck_name)}</h1>
                <p class="text-gray-600">
                    Zeitraum: {format_date(start_date)} bis {format_date(end_date)}
                </p>
            </header>

            <!-- Lernzusammenfassung -->
            <div class="bg-white rounded-lg shadow-md p-6 mb-6">
                <h2 class="text-xl font-semibold mb-4">Lernzusammenfassung</h2>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div class="bg-blue-50 p-4 rounded-lg">
                        <h3 class="text-sm font-medium text-blue-800">Gelernte Karten</h3>
                        <p class="text-3xl font-bold">{total_studied_cards}</p>
                    </div>
                    <div class="bg-green-50 p-4 rounded-lg">
                        <h3 class="text-sm font-medium text-green-800">Erfolgreiche Lerntage</h3>
                        <p class="text-3xl font-bold">{successful_days}/{total_days}</p>
                    </div>
                    <div class="bg-yellow-50 p-4 rounded-lg">
                        <h3 class="text-sm font-medium text-yellow-800">∅ Karten/Tag</h3>
                        <p class="text-3xl font-bold">{avg_cards_per_day:.1f}</p>
                    </div>
                </div>
            </div>
            
            <!-- Levelverlauf -->
            <div class="bg-white rounded-lg shadow-md p-6 mb-6">
                <h2 class="text-xl font-semibold mb-4">Levelverlauf</h2>
    """

        # Levelverlauf als Tabelle anzeigen - mit Debugging-Infos
        print(f"Study Tracker: Leveländerungen für Bericht: {len(level_history_data)}")
        
        if level_history_data and len(level_history_data) > 0:
            html += """
                <table class="level-history-table">
                    <thead>
                        <tr>
                            <th>Datum</th>
                            <th>Änderungstyp</th>
                            <th>Altes Level</th>
                            <th>Neues Level</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            
            for item in level_history_data:
                change_date = item.get('date', '')
                change_type = item.get('change_type', '')
                old_level = item.get('old_level', 0)
                new_level = item.get('new_level', 0)
                formatted_date = item.get('formatted_date', change_date)
                
                # Menschenlesbarer Änderungstyp
                change_type_text = "Unbekannt"
                row_class = ""

                if change_type == 'up':
                    change_type_text = "Level-Aufstieg"
                    row_class = "bg-green-50"
                elif change_type == 'down':
                    change_type_text = "Level-Abstieg"
                    row_class = "bg-red-50"
                elif change_type == 'init':
                    change_type_text = "Initialisierung"
                    row_class = "bg-blue-50"
                elif change_type == 'new_period':
                    change_type_text = "Neuer Abschnitt"
                    row_class = "bg-yellow-50"
                elif change_type == 'reset_period':
                    change_type_text = "Abschnitt zurückgesetzt"
                    row_class = "bg-yellow-50"
                elif change_type == 'early_completion':
                    change_type_text = "Frühzeitige Vervollständigung"
                    row_class = "bg-green-50"
                
                html += f"""
                        <tr class="{row_class}">
                            <td>{formatted_date}</td>
                            <td>{change_type_text}</td>
                            <td class="text-center">{old_level}</td>
                            <td class="text-center font-bold">{new_level}</td>
                        </tr>
                """
            
            html += """
                    </tbody>
                </table>
            """
        else:
            html += """
                <div class="bg-gray-100 p-4 rounded text-gray-600 text-center">
                    Keine Level-Änderungen im ausgewählten Zeitraum
                </div>
            """

        html += """
            </div>

            
            <!-- Tägliche Lernstatistik -->
            <div class="bg-white rounded-lg shadow-md p-6">
                <h2 class="text-xl font-semibold mb-4">Tägliche Lernstatistik</h2>
                <div class="overflow-x-auto">
                    <table class="w-full text-sm" id="daily-stats-table">
                        <thead>
                            <tr>
                                <th class="text-left p-2 border-b">Datum</th>
                                <th class="text-center p-2 border-b">Fällig</th>
                                <th class="text-center p-2 border-b">Gelernt</th>
                                <th class="text-center p-2 border-b">Status</th>
                            </tr>
                        </thead>
                        <tbody>
    """
        
        # Tägliche Statistiken in HTML einfügen
        sorted_dates = sorted(daily_stats.keys(), reverse=True)
        row_index = 0
        
        for date_str in sorted_dates:
            stats = daily_stats[date_str]
            formatted_date = format_date(date_str)
            
            # Nur Tage mit Lernaktivität oder fälligen Karten anzeigen
            if stats['cards_due'] > 0 or stats['cards_studied'] > 0:
                success_class = "text-green-600" if stats['success'] else "text-red-600"
                success_text = "✓" if stats['success'] else "✗"
                expand_id = f"expand-{row_index}"
                
                # Haupt-Tabellenzeile (Tagesübersicht)
                html += f"""
                            <tr class="expand-trigger daily-stats-row hover:bg-gray-50" data-target="{expand_id}">
                                <td class="p-2 border-b">{formatted_date}</td>
                                <td class="text-center p-2 border-b">{stats['cards_due']}</td>
                                <td class="text-center p-2 border-b">{stats['cards_studied']}</td>
                                <td class="text-center p-2 border-b {success_class} font-bold">{success_text}</td>
                            </tr>
                """
                
                # Ausklappbare Inhaltszeile
                html += f"""
                            <tr id="{expand_id}" class="expandable-row">
                                <td colspan="4" class="p-0 border-b">
                                    <div class="expandable-content">
                                        <h4 class="font-medium mb-3">Lerndetails für {formatted_date}</h4>
                                        
                                        <!-- Kartendetails als Tabelle -->
                                        <div class="card-list-container bg-white p-4 rounded border mb-4">
                """
                
                # Kartendetails, falls vorhanden
                cards = day_details.get(date_str, [])
                if cards and len(cards) > 0:
                    html += """
                                            <table class="min-w-full divide-y divide-gray-200">
                                                <thead class="bg-gray-50">
                                                    <tr>
                                                        <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Karte</th>
                                                        <th scope="col" class="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">Aktionen</th>
                                                    </tr>
                                                </thead>
                                                <tbody class="bg-white divide-y divide-gray-200">
                    """
                    
                    # Für jede Karte eine Zeile mit Klick-Funktionalität
                    for card_index, card in enumerate(cards):
                        card_id = card.get('card_id', '')
                        card_title = card.get('card_title', 'Unbekannte Karte')
                        chat_link = card.get('chat_link', '')
                        
                        # Jede Karte bekommt ihr eigenes Kompetenz-Div
                        comp_id = f"comp-{row_index}-{card_index}"
                        
                        # Prüfe, ob Validierungscodes für diese Karte vorhanden sind
                        validation_codes = card.get('validation_codes', [])
                        has_validation_codes = len(validation_codes) > 0
                        
                        html += f"""
                                                    <tr class="card-row hover:bg-blue-50 cursor-pointer" data-target="{comp_id}" data-card-id="{card_id}">
                                                        <td class="px-4 py-3 text-sm text-gray-900">
                                                            <div class="flex items-center">
                                                                <span>{escape_html(card_title)}</span>
                                                                <!-- Falls der Titel nur eine ID ist, zeige einen Hinweis -->
                                                                {f'<span class="ml-2 text-xs text-gray-500">(verschoben/archiviert)</span>' if card_title.startswith('Karte') else ''}
                        """
                        
                        # ChatGPT-Link direkt nach dem Kartentitel
                        if chat_link:
                            html += f"""
                                                                <a href="{escape_html(chat_link)}" target="_blank" class="inline-flex items-center ml-2" onclick="event.stopPropagation();">
                                                                    <span class="chatgpt-badge">
                                                                        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
                                                                        ChatGPT
                                                                    </span>
                                                                </a>
                                                            </div>
                                                            <div class="chatgpt-url" title="{escape_html(chat_link)}">
                                                                {escape_html(chat_link)}
                                                            </div>
                            """
                        else:
                            html += """
                                                            </div>
                            """
                        
                        html += """
                                                        </td>
                                                        <td class="px-4 py-3 whitespace-nowrap text-center">
                                                            <button class="bg-blue-100 hover:bg-blue-200 text-blue-700 font-bold py-1 px-2 rounded text-xs">
                                                                Details
                                                            </button>
                                                        </td>
                                                    </tr>
                        """
                    
                    html += """
                                                </tbody>
                                            </table>
                    """
                else:
                    html += """
                                            <p class="text-gray-500 py-4 text-center">Keine Kartendetails für diesen Tag verfügbar.</p>
                    """
                
                html += """
                                        </div>
                                        
                                        <!-- Container für Kompetenzvisualisierung -->
                                        <div class="competency-container">
                """
                
                # Für jede Karte ein verstecktes Kompetenz-Div erstellen
                if cards and len(cards) > 0:
                    for card_index, card in enumerate(cards):
                        card_id = card.get('card_id', '')
                        card_title = card.get('card_title', 'Unbekannte Karte')
                        comp_id = f"comp-{row_index}-{card_index}"
                        
                        # Sammle Validierungscodes für diese Karte
                        card_validation_codes = []
                        for v_code in validation_data:
                            if str(v_code.get('cardId', '')) == str(card_id):
                                card_validation_codes.append(v_code)
                        
                        has_validation_codes = len(card_validation_codes) > 0
                        
                        html += f"""
                                            <!-- Kompetenzvisualisierung für Karte {card_index + 1} -->
                                            <div id="{comp_id}" class="competency-view bg-blue-50 p-4 rounded border border-blue-200 mb-3 hidden">
                                                <div class="flex justify-between items-center mb-3">
                                                    <h5 class="font-medium text-blue-800">Kompetenzentwicklung: {escape_html(card_title)}</h5>
                                                    <button class="close-competency-view text-gray-500 hover:bg-gray-200 p-1 rounded-full" data-comp-id="{comp_id}">
                                                        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                                                            <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
                                                        </svg>
                                                    </button>
                                                </div>
                        """
                        
                        if has_validation_codes:
                            # Tabelle für Validierungscodes
                            html += """
                                                <div class="mb-4">
                                                    <h6 class="font-medium text-sm mb-2">Vorhandene Validierungscodes:</h6>
                                                    <table class="validation-code-table">
                                                        <thead>
                                                            <tr>
                                                                <th>Datum</th>
                                                                <th>Code</th>
                                                                <th>Schwierigkeit</th>
                                                                <th>Korrektheit</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                            """
                            
                            # Sortiere nach Datum
                            sorted_codes = sorted(card_validation_codes, key=lambda x: x.get('date', ''))
                            
                            for i, code_data in enumerate(sorted_codes):
                                code = code_data.get('validationCode', '')
                                date = code_data.get('date', '')
                                correct = code_data.get('correctPercent', 0)
                                difficulty = code_data.get('difficulty', 0)
                                
                                # Formatiere das Datum
                                formatted_date = date
                                try:
                                    if date:
                                        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
                                        formatted_date = format_date(date_obj)
                                except ValueError:
                                    pass
                                
                                html += f"""
                                                            <tr>
                                                                <td>{formatted_date}</td>
                                                                <td class="font-mono">{code}</td>
                                                                <td class="text-center">{difficulty}</td>
                                                                <td class="text-center">{correct}%</td>
                                                            </tr>
                                """
                            
                            html += """
                                                        </tbody>
                                                    </table>
                                                </div>
                            """
                        else:
                            html += """
                                                <div class="bg-white rounded border p-3 text-center text-gray-500">
                                                    Keine Validierungscodes für diese Karte vorhanden.
                                                </div>
                            """
                        
                        html += """
                                            </div>
                        """
                
                html += """
                                        </div>
                                    </div>
                                </td>
                            </tr>
                """
                
                row_index += 1
        
        # Wenn keine Statistiken vorhanden sind
        if not sorted_dates:
            html += """
                            <tr>
                                <td colspan="4" class="text-center p-4 text-gray-500">
                                    Keine Lernstatistiken im ausgewählten Zeitraum
                                </td>
                            </tr>
            """
        
        html += """
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <script>
        """
        
        # Füge verbesserte JavaScript-Funktionen ein
        js_functions = """
    // Definiere globale Variablen für die Daten
    window.levelChangesData = """ + level_history_json + """;
    window.deckName = """ + json.dumps(deck_name) + """;
    window.validationData = """ + validation_data_json + """;

    function toggleRow(rowId) {
        console.log(`toggleRow aufgerufen für: ${rowId}`);
        
        const row = document.getElementById(rowId);
        if (!row) {
            console.warn(`Row not found: ${rowId}`);
            return;
        }
        
        // Prüfe, ob wir die Zeile gerade öffnen oder schließen
        const isOpening = window.getComputedStyle(row).display !== 'table-row';
        
        // Debug-Log zum besseren Nachvollziehen
        console.log(`Zeile ${rowId} wird ${isOpening ? "geöffnet" : "geschlossen"}`);
        
        // Wenn wir eine neue Zeile öffnen, schließe alle anderen zuerst
        if (isOpening) {
            // Schließe alle anderen geöffneten Zeilen
            document.querySelectorAll('.expandable-row').forEach(openRow => {
                if (openRow.id !== rowId && window.getComputedStyle(openRow).display === 'table-row') {
                    console.log(`Schließe andere Zeile: ${openRow.id}`);
                    openRow.style.display = 'none';
                }
            });
            
            // Schließe alle Kompetenzansichten global
            document.querySelectorAll('.competency-view').forEach(view => {
                view.classList.add('hidden');
            });
            
            // Öffne die neue Zeile
            row.style.display = 'table-row';
        } else {
            // Zeile schließen
            row.style.display = 'none';
            
            // Alle Kompetenzansichten innerhalb dieser Zeile schließen
            row.querySelectorAll('.competency-view').forEach(view => {
                view.classList.add('hidden');
            });
        }
    }

    /**
    * Verbesserte Initialisierungsfunktion, die Event-Handler korrekt zuweist
    * für Tageszeilen und Kartenzeilen
    */
    function initializeEventHandlers() {
        console.log("Initialisiere Event-Handler...");
        
        // Event-Handler für Tageszeilen
        const dayTriggers = document.querySelectorAll('.expand-trigger');
        console.log(`Gefunden: ${dayTriggers.length} Tageszeilen`);
        
        dayTriggers.forEach((trigger, index) => {
            console.log(`Füge Event-Handler für Tageszeile ${index + 1} hinzu`);
            
            // Entferne bestehende Event-Listener (für den Fall einer Re-Initialisierung)
            trigger.removeEventListener('click', handleDayRowClick);
            
            // Füge neuen Event-Listener hinzu
            trigger.addEventListener('click', handleDayRowClick);
        });
        
        // Setup für Kartenzeilen separat aufrufen
        setupCardRowEventListeners();
    }

    /**
    * Event-Handler-Funktion für Tageszeilen-Klicks
    * Durch separierte Funktion zur besseren Fehlerdiagnose
    */
    function handleDayRowClick(event) {
        const rowId = this.getAttribute('data-target');
        console.log(`Tageszeile geklickt: Target = ${rowId}`);
        toggleRow(rowId);
    }

    /**
    * Verbesserte Funktion zum Einrichten der Karten-Event-Handler
    */
    function setupCardRowEventListeners() {
        // Alle Kartenzeilen finden
        const cardRows = document.querySelectorAll('.card-row');
        console.log(`Gefunden: ${cardRows.length} Kartenzeilen`);
        
        // Event-Listener für jede Zeile hinzufügen
        cardRows.forEach((row, index) => {
            console.log(`Füge Event-Handler für Kartenzeile ${index + 1} hinzu`);
            
            // Entferne bestehende Event-Listener (für den Fall einer Re-Initialisierung)
            row.removeEventListener('click', handleCardRowClick);
            
            // Füge neuen Event-Listener hinzu
            row.addEventListener('click', handleCardRowClick);
        });
        
        // Event-Listener für Schließen-Buttons
        document.querySelectorAll('.close-competency-view').forEach((btn, index) => {
            console.log(`Füge Event-Handler für Schließen-Button ${index + 1} hinzu`);
            
            // Entferne bestehende Event-Listener
            btn.removeEventListener('click', handleCloseButtonClick);
            
            // Füge neuen Event-Listener hinzu
            btn.addEventListener('click', handleCloseButtonClick);
        });
    }

    /**
    * Event-Handler-Funktion für Kartenzeilen-Klicks
    */
    function handleCardRowClick(event) {
        // IDs holen
        const compId = this.getAttribute('data-target');
        console.log(`Kartenzeile geklickt: Target = ${compId}`);
        
        // Alle Kompetenz-Divs schließen
        document.querySelectorAll('.competency-view').forEach(menu => {
            menu.classList.add('hidden');
        });
        
        // Das ausgewählte Kompetenz-Div öffnen
        const compDiv = document.getElementById(compId);
        if (compDiv) {
            compDiv.classList.remove('hidden');
            
            // Scrolle zum Kompetenzbereich
            compDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else {
            console.warn(`Kompetenz-Div nicht gefunden: ${compId}`);
        }
    }

    /**
    * Event-Handler-Funktion für Schließen-Button-Klicks
    */
    function handleCloseButtonClick(event) {
        // Verhindern, dass der Klick an die Kartenzeile weitergeleitet wird
        event.stopPropagation();
        
        const compId = this.getAttribute('data-comp-id');
        console.log(`Schließen-Button geklickt: Target = ${compId}`);
        
        const compDiv = document.getElementById(compId);
        if (compDiv) {
            compDiv.classList.add('hidden');
        } else {
            console.warn(`Kompetenz-Div nicht gefunden: ${compId}`);
        }
    }

    // Initialisierung nach DOM-Laden
    document.addEventListener('DOMContentLoaded', function() {
        console.log("DOM vollständig geladen");
        
        // Event-Handler initialisieren
        initializeEventHandlers();
        
        // Hilfsklasse für Debugging hinzufügen
        document.body.classList.add('event-debug-active');
    });

    // Hilfe-Funktion für den Benutzer, die aufgerufen werden kann, wenn die UI nicht richtig funktioniert
    window.reinitializeEvents = function() {
        console.log("Event-Handler werden neu initialisiert...");
        initializeEventHandlers();
        return "Event-Handler wurden neu initialisiert";
    };
    """
        
        html += js_functions
        
        html += """
        </script>
    </body>
    </html>
    """
        
        return html
    
    def updated_html_generator(self, date_str, formatted_date, stats, day_details, validation_data_json, row_index):
        """
        Generiert den HTML-Code für die ausklappbaren Zeilen der Tagesstatistik
        mit korrekter Darstellung des ChatGPT-Links neben dem Kartentitel
        """
        success_class = "text-green-600" if stats['success'] else "text-red-600"
        success_text = "✓" if stats['success'] else "✗"
        expand_id = f"expand-{row_index}"
        
        # Haupt-Tabellenzeile (Tagesübersicht)
        html = f"""
                            <tr class="expand-trigger daily-stats-row hover:bg-gray-50" data-target="{expand_id}">
                                <td class="p-2 border-b">{formatted_date}</td>
                                <td class="text-center p-2 border-b">{stats['cards_due']}</td>
                                <td class="text-center p-2 border-b">{stats['cards_studied']}</td>
                                <td class="text-center p-2 border-b {success_class} font-bold">{success_text}</td>
                            </tr>
            """
        
        # Ausklappbare Inhaltszeile
        html += f"""
                            <tr id="{expand_id}" class="expandable-row">
                                <td colspan="4" class="p-0 border-b">
                                    <div class="expandable-content">
                                        <h4 class="font-medium mb-3">Lerndetails für {formatted_date}</h4>
                                        
                                        <!-- Erste Menüebene: Kartendetails als Tabelle -->
                                        <div class="card-list-container bg-white p-4 rounded border mb-4">
            """
        
        # Kartendetails, falls vorhanden
        cards = day_details.get(date_str, [])
        if cards and len(cards) > 0:
            html += """
                                            <table class="min-w-full divide-y divide-gray-200">
                                                <thead class="bg-gray-50">
                                                    <tr>
                                                        <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Karte</th>
                                                        <th scope="col" class="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">Aktionen</th>
                                                    </tr>
                                                </thead>
                                                <tbody class="bg-white divide-y divide-gray-200">
                """
            
            # Für jede Karte eine Zeile mit Klick-Funktionalität
            for card_index, card in enumerate(cards):
                card_id = card.get('card_id', '')
                card_title = card.get('card_title', 'Unbekannte Karte')
                chat_link = card.get('chat_link', '')
                
                # Debug-Ausgabe für diese Karte
                print(f"Study Tracker: Card in HTML: {card_id} - '{card_title}' - ChatGPT: {bool(chat_link)}")
                
                # Jede Karte bekommt ihr eigenes Kompetenz-Div
                comp_id = f"comp-{row_index}-{card_index}"
                
                html += f"""
                                                    <tr class="card-row hover:bg-blue-50 cursor-pointer" data-target="{comp_id}" data-card-id="{card_id}">
                                                        <td class="px-4 py-3 text-sm text-gray-900">
                                                            <div class="flex items-center">
                                                                <span>{escape_html(card_title)}</span>
                    """
                
                # FIXIERT: ChatGPT-Link direkt nach dem Kartentitel in einer Flex-Box
                if chat_link:
                    html += f"""
                            <a href="{escape_html(chat_link)}" target="_blank" class="inline-flex items-center ml-2" onclick="event.stopPropagation();">
                                <span class="chatgpt-badge">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
                                    ChatGPT
                                </span>
                            </a>
                            <div class="text-xs text-gray-500 mt-1 overflow-hidden" style="font-size: 8px; word-break: break-all;">
                                {escape_html(chat_link)}
                            </div>
                        """
                
                # Ende der Flex-Box
                html += """
                                                            </div>
                                                        </td>
                                                        <td class="px-4 py-3 whitespace-nowrap text-center">
                                                            <button class="bg-blue-100 hover:bg-blue-200 text-blue-700 font-bold py-1 px-2 rounded text-xs">
                                                                Details
                                                            </button>
                                                        </td>
                                                    </tr>
                    """
            
            html += """
                                                </tbody>
                                            </table>
                """
        else:
            html += """
                                            <p class="text-gray-500 py-4 text-center">Keine Kartendetails für diesen Tag verfügbar.</p>
                """
        
        html += """
                                        </div>
                                        
                                        <!-- Zweite Menüebene: Container für Kompetenzvisualisierung -->
                                        <div class="competency-container">
            """
        
        # Für jede Karte ein verstecktes Kompetenz-Div erstellen
        if cards and len(cards) > 0:
            # Wandle validation_data_json in Python-Objekt um für die Filterung
            try:
                validation_data = json.loads(validation_data_json)
            except (json.JSONDecodeError, TypeError):
                validation_data = []
                
            for card_index, card in enumerate(cards):
                card_id = card.get('card_id', '')
                card_title = card.get('card_title', 'Unbekannte Karte')
                comp_id = f"comp-{row_index}-{card_index}"
                
                # RICHTIG: Filtere die Validierungscodes, um nur die für diese spezifische Karte zu zeigen
                card_validation_codes = [v for v in validation_data if str(v.get('cardId', '')) == str(card_id)]
                
                has_validation_codes = len(card_validation_codes) > 0
                
                html += f"""
                                            <!-- Kompetenzvisualisierung für Karte {card_index + 1} -->
                                            <div id="{comp_id}" class="competency-view bg-blue-50 p-4 rounded border border-blue-200 mb-3 hidden">
                                                <div class="flex justify-between items-center mb-3">
                                                    <h5 class="font-medium text-blue-800">Kompetenzentwicklung: {escape_html(card_title)}</h5>
                                                    <button class="close-competency-view text-gray-500 hover:bg-gray-200 p-1 rounded-full" data-comp-id="{comp_id}">
                                                        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                                                            <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
                                                        </svg>
                                                    </button>
                                                </div>
                    """
                
                if has_validation_codes:
                    # Tabelle für Validierungscodes
                    html += """
                                                <div class="mb-4">
                                                    <h6 class="font-medium text-sm mb-2">Vorhandene Validierungscodes:</h6>
                                                    <table class="validation-code-table">
                                                        <thead>
                                                            <tr>
                                                                <th>Datum</th>
                                                                <th>Code</th>
                                                                <th>Schwierigkeit</th>
                                                                <th>Korrektheit</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                                """
                    
                    # Sortiere nach Datum
                    sorted_codes = sorted(card_validation_codes, key=lambda x: x.get('date', ''))
                    
                    for i, code_data in enumerate(sorted_codes):
                        code = code_data.get('validationCode', '')
                        date = code_data.get('date', '')
                        correct = code_data.get('correctPercent', 0)
                        difficulty = code_data.get('difficulty', 0)
                        
                        # Formatiere das Datum
                        formatted_date = date
                        try:
                            if date:
                                date_obj = datetime.strptime(date, "%Y-%m-%d").date()
                                formatted_date = format_date(date_obj)
                        except ValueError:
                            pass
                        
                        html += f"""
                                                            <tr>
                                                                <td>{formatted_date}</td>
                                                                <td class="font-mono">{code}</td>
                                                                <td class="text-center">{difficulty}</td>
                                                                <td class="text-center">{correct}%</td>
                                                            </tr>
                                """
                    
                    html += """
                                                        </tbody>
                                                    </table>
                                                </div>
                                """
                else:
                    html += """
                                                <div class="bg-white rounded border p-3 text-center text-gray-500">
                                                    Keine Validierungscodes für diese Karte vorhanden.
                                                </div>
                                """
                
                html += """
                                            </div>
                            """
        
        html += """
                                        </div>
                                    </div>
                                </td>
                            </tr>
            """
        
        return html

    def load_all_cards_with_data(self, deck_id, start_date, end_date):
        """
        Lädt alle Karten mit ihren zugehörigen ChatGPT-Links und Validierungscodes direkt aus der Datenbank.
        Diese Methode umgeht die bisherigen Abstraktionsschichten und sorgt für eine konsistente Datenzuordnung.
        
        Args:
            deck_id: ID des Decks
            start_date: Startdatum im Format YYYY-MM-DD
            end_date: Enddatum im Format YYYY-MM-DD
            
        Returns:
            dict: Dictionary mit Karten-IDs als Schlüssel und Karteninformationen als Werte
        """
        try:
            print(f"Study Tracker: Lade alle Karteninformationen für Deck {deck_id}, Zeitraum {start_date} bis {end_date}")
            
            cards_dict = {}
            
            # 1. Hole alle gelernten Karten im Zeitraum
            cursor = self.db.conn.execute("""
                SELECT DISTINCT s.card_id, s.date
                FROM studied_cards s
                WHERE s.deck_id = ? AND s.date BETWEEN ? AND ?
            """, (deck_id, start_date, end_date))
            
            studied_cards = cursor.fetchall()
            print(f"Study Tracker: Gefunden {len(studied_cards)} gelernte Karten im Zeitraum")
            
            for card_data in studied_cards:
                card_id = str(card_data[0])
                studied_date = card_data[1]
                
                # Initialisiere Karten-Dictionary, wenn noch nicht vorhanden
                if card_id not in cards_dict:
                    cards_dict[card_id] = {
                        'card_id': card_id,
                        'card_title': None,
                        'chat_link': None,
                        'validation_codes': [],
                        'studied_dates': []
                    }
                
                # Füge Lerndatum hinzu
                cards_dict[card_id]['studied_dates'].append(studied_date)
            
            # 2. Hole Kartentitel für alle gefundenen Karten
            if cards_dict:
                card_ids = list(cards_dict.keys())
                placeholders = ','.join(['?'] * len(card_ids))
                
                try:
                    # Versuche Titel aus validation_codes zu holen
                    cursor = self.db.conn.execute(f"""
                        SELECT card_id, card_title
                        FROM validation_codes
                        WHERE card_id IN ({placeholders}) AND card_title IS NOT NULL
                        GROUP BY card_id
                    """, card_ids)
                    
                    for row in cursor.fetchall():
                        card_id = str(row[0])
                        if card_id in cards_dict:
                            cards_dict[card_id]['card_title'] = row[1]
                    
                    # Versuche Titel aus chat_links zu holen, wenn noch nicht gefunden
                    cursor = self.db.conn.execute(f"""
                        SELECT card_id, card_title
                        FROM chat_links
                        WHERE card_id IN ({placeholders}) AND card_title IS NOT NULL
                    """, card_ids)
                    
                    for row in cursor.fetchall():
                        card_id = str(row[0])
                        if card_id in cards_dict and not cards_dict[card_id]['card_title']:
                            cards_dict[card_id]['card_title'] = row[1]
                    
                    # Fallback für fehlende Titel
                    for card_id in cards_dict:
                        if not cards_dict[card_id]['card_title']:
                            cards_dict[card_id]['card_title'] = f"Karte {card_id}"
                except Exception as e:
                    print(f"Study Tracker: Fehler beim Abrufen der Kartentitel: {e}")
                    # Setze Fallback-Titel
                    for card_id in cards_dict:
                        if not cards_dict[card_id]['card_title']:
                            cards_dict[card_id]['card_title'] = f"Karte {card_id}"
            
            # 3. Hole ChatGPT-Links für alle gefundenen Karten
            if cards_dict:
                card_ids = list(cards_dict.keys())
                placeholders = ','.join(['?'] * len(card_ids))
                
                try:
                    cursor = self.db.conn.execute(f"""
                        SELECT card_id, link
                        FROM chat_links
                        WHERE card_id IN ({placeholders})
                    """, card_ids)
                    
                    for row in cursor.fetchall():
                        card_id = str(row[0])
                        if card_id in cards_dict:
                            cards_dict[card_id]['chat_link'] = row[1]
                            print(f"Study Tracker: ChatGPT-Link gefunden für Karte {card_id}: {row[1][:30]}...")
                except Exception as e:
                    print(f"Study Tracker: Fehler beim Abrufen der ChatGPT-Links: {e}")
            
            # 4. Hole Validierungscodes für alle gefundenen Karten
            if cards_dict:
                card_ids = list(cards_dict.keys())
                placeholders = ','.join(['?'] * len(card_ids))
                
                try:
                    cursor = self.db.conn.execute(f"""
                        SELECT card_id, date, code, correct_percent, difficulty
                        FROM validation_codes
                        WHERE card_id IN ({placeholders})
                        ORDER BY date
                    """, card_ids)
                    
                    for row in cursor.fetchall():
                        card_id = str(row[0])
                        if card_id in cards_dict:
                            # Extrahiere Daten
                            date = row[1]
                            code = row[2]
                            correct_percent = row[3] if row[3] is not None else (int(code[:2]) if len(code) >= 2 else 0)
                            difficulty = row[4] if row[4] is not None else (int(code[2:4]) if len(code) >= 4 else 0)
                            
                            # Füge Validierungscode hinzu
                            cards_dict[card_id]['validation_codes'].append({
                                'date': date,
                                'validationCode': code,
                                'correctPercent': correct_percent,
                                'difficulty': difficulty
                            })
                            
                            print(f"Study Tracker: Validierungscode gefunden für Karte {card_id}: {code} vom {date}")
                except Exception as e:
                    print(f"Study Tracker: Fehler beim Abrufen der Validierungscodes: {e}")
            
            # Ausgabe der Zusammenfassung
            total_codes = sum(len(card_data['validation_codes']) for card_data in cards_dict.values())
            total_links = sum(1 for card_data in cards_dict.values() if card_data['chat_link'])
            
            print(f"Study Tracker: Insgesamt geladen: {len(cards_dict)} Karten, {total_codes} Validierungscodes, {total_links} ChatGPT-Links")
            
            return cards_dict
        except Exception as e:
            print(f"Study Tracker: Fehler beim Laden der Karteninformationen: {e}")
            traceback.print_exc()
            return {}
    
    def generate_report_with_direct_data(self, deck_id, start_date, end_date):
        """
        Generiert einen vollständigen HTML-Bericht für den angegebenen Zeitraum
        mit direktem Datenbankzugriff für zuverlässigere Ergebnisse und Fortschrittsanzeige
        
        Args:
            deck_id: ID des Decks
            start_date: Startdatum im Format YYYY-MM-DD
            end_date: Enddatum im Format YYYY-MM-DD
                
        Returns:
            str: HTML-Inhalt des Berichts
        """
        try:
            # Erstelle Fortschrittsdialog
            progress = QProgressDialog("Generiere Bericht...", "Abbrechen", 0, 100, mw)
            progress.setWindowTitle("Study Tracker")
            progress.setWindowModality(get_qt_enum(Qt.WindowModality, "WindowModal"))
            progress.setValue(0)
            progress.show()
            progress.setValue(3)
            progress.setLabelText("Synchronisiere Kartendaten...")
            QApplication.processEvents()
            
            try:
                # Verwende die neue Vorbereitungsfunktion
                self.db.prepare_for_report(deck_id, start_date, end_date)
            except Exception as e:
                print(f"Study Tracker: Fehler bei der Berichtsvorbereitung: {e}")
                traceback.print_exc()

            # Validiere Daten
            progress.setValue(5)
            progress.setLabelText("Validiere Daten...")
            QApplication.processEvents()
            
            validation_errors = self.validate_data_before_report(deck_id, start_date, end_date)
            if validation_errors:
                error_msg = "\n".join(validation_errors)
                progress.close()
                return self._generate_error_report(f"Fehler bei der Datenvalidierung:\n{error_msg}")
            
            # Hole Deckname
            progress.setValue(10)
            progress.setLabelText("Lade Deckdaten...")
            QApplication.processEvents()
            
            deck_name = "Unbekannter Stapel"
            if mw and mw.col:
                try:
                    deck = mw.col.decks.get(deck_id)
                    if deck:
                        deck_name = deck['name']
                except Exception as e:
                    print(f"Study Tracker: Fehler beim Abrufen des Decknamens: {e}")
            
            # Aktualisiere Validierungscodes und ChatGPT-Links vor der Berichterstellung
            progress.setValue(20)
            progress.setLabelText("Aktualisiere Kartendaten...")
            QApplication.processEvents()
            
            try:
                print("Study Tracker: Aktualisiere Validierungscodes und ChatGPT-Links vor Berichtserstellung...")
                collector = StudyStatisticsCollector(self.db)
                collector.parse_validation_codes_from_cards()
                print("Study Tracker: Aktualisierung abgeschlossen")
            except Exception as e:
                print(f"Study Tracker: Fehler bei der Aktualisierung vor Berichtserstellung: {e}")
                traceback.print_exc()
            
            # NEUE METHODE: Lade alle Karten mit ihren Daten direkt aus der Datenbank
            progress.setValue(40)
            progress.setLabelText("Lade Karteninformationen...")
            QApplication.processEvents()
            
            cards_dict = self.load_all_cards_with_data(deck_id, start_date, end_date)
            
            # Hole Level-Historie DIREKT
            progress.setValue(50)
            progress.setLabelText("Lade Level-Historie...")
            QApplication.processEvents()
            
            print(f"Study Tracker: Hole Level-Historie für Bericht...")
            level_history = self.get_level_history_direct(deck_id, start_date, end_date)
            print(f"Study Tracker: Gefunden: {len(level_history)} Level-Änderungen für Bericht")
            
            # Konvertiere in JSON-Format für JavaScript
            level_history_json = json.dumps(level_history)
            
            # Bereite Tagesstatistiken und Kartendetails vor
            progress.setValue(60)
            progress.setLabelText("Bereite Tagesstatistiken vor...")
            QApplication.processEvents()
            
            daily_stats = {}
            day_details = {}
            
            # Bereite tägliche Statistiken vor
            current_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            
            while current_date <= end_date_obj:
                date_str = current_date.strftime("%Y-%m-%d")
                stats = self.db.get_daily_stats(date_str, deck_id)
                
                daily_stats[date_str] = {
                    'cards_due': stats['cards_due'],
                    'cards_studied': stats['cards_studied'],
                    'success': stats['cards_due'] > 0 and stats['cards_studied'] >= stats['cards_due']
                }
                
                # Finde Karten, die an diesem Tag gelernt wurden
                cards_for_day = []
                
                for card_id, card_data in cards_dict.items():
                    if date_str in card_data['studied_dates']:
                        cards_for_day.append({
                            'card_id': card_id,
                            'card_title': card_data['card_title'],
                            'chat_link': card_data['chat_link'],
                            'validation_codes': card_data['validation_codes'],
                            'time_spent': 0  # Default-Wert, könnte durch eine Abfrage ersetzt werden
                        })
                
                if cards_for_day:
                    day_details[date_str] = cards_for_day
                
                current_date += timedelta(days=1)
            
            # Erstelle validationData für JavaScript
            progress.setValue(80)
            progress.setLabelText("Bereite Validierungsdaten vor...")
            QApplication.processEvents()
            
            validation_data = []
            
            for card_id, card_data in cards_dict.items():
                for code in card_data['validation_codes']:
                    validation_data.append({
                        'date': code['date'],
                        'validationCode': code['validationCode'],
                        'correctPercent': code['correctPercent'],
                        'difficulty': code['difficulty'],
                        'cardId': card_id,
                        'cardTitle': card_data['card_title'],
                        'chatLink': card_data['chat_link']
                    })
            
            validation_data_json = json.dumps(validation_data)
            
            for card_id, card_data in cards_dict.items():
                # Stelle sicher, dass jede Karte einen benutzerfreundlichen Titel hat
                if not card_data['card_title'] or card_data['card_title'].startswith("173800"):
                    # Wenn der Titel fehlt oder wie eine ID aussieht
                    card_data['card_title'] = ValidationCodeHandler(self.db).get_card_title(card_id)
                    
                    # Wenn immer noch eine ID-ähnliche Zeichenfolge, formatiere sie benutzerfreundlich
                    if card_data['card_title'].startswith("173800"):
                        short_id = card_id[-8:] if len(card_id) > 8 else card_id
                        card_data['card_title'] = f"Karte #{short_id} (nicht mehr verfügbar)"

            # Erzeuge den HTML-Bericht
            progress.setValue(90)
            progress.setLabelText("Generiere HTML-Bericht...")
            QApplication.processEvents()
            
            html_content = self._generate_html_report(
                deck_name,
                validation_data_json,
                level_history_json,
                day_details,
                start_date,
                end_date,
                deck_id
            )
            
            progress.setValue(100)
            progress.close()
            
            return html_content
        except Exception as e:
            if 'progress' in locals():
                progress.close()
                
            print(f"Study Tracker: Fehler bei der Berichtsgenerierung: {e}")
            traceback.print_exc()
            
            # Erstelle minimalen Fehlerbericht
            return self._generate_error_report(str(e))
            
    def _generate_error_report(self, error_message):
        """Generiert einen HTML-Fehlerbericht"""
        error_html = f"""<!DOCTYPE html>
        <html>
        <head><title>Fehler bei der Berichtsgenerierung</title></head>
        <body>
            <h1>Fehler bei der Berichtsgenerierung</h1>
            <p>Es ist ein Fehler aufgetreten: {escape_html(error_message)}</p>
            <p>Bitte überprüfen Sie die Anki-Konsole für weitere Details.</p>
        </body>
        </html>"""
        return error_html
    
    def validate_data_before_report(self, deck_id, start_date, end_date):
        """Validiert Daten vor der Berichterstellung, um Probleme frühzeitig zu erkennen"""
        validation_errors = []
        
        # 1. Prüfe, ob deck_id gültig ist
        if not deck_id or deck_id <= 0:
            validation_errors.append("Ungültige Deck-ID")
        
        # 2. Prüfe Datumsformat
        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            validation_errors.append("Ungültiges Datumsformat (YYYY-MM-DD erforderlich)")
            return validation_errors  # Früher zurückkehren, da weitere Prüfungen fehlschlagen würden
        
        # 3. Prüfe Zeitraum-Logik
        if start_date > end_date:
            validation_errors.append("Startdatum liegt nach Enddatum")
            
        # 4. Prüfe maximalen Zeitraum (optional)
        date_diff = (end_date_obj - start_date_obj).days
        if date_diff > 366:  # Mehr als ein Jahr
            validation_errors.append(f"Der gewählte Zeitraum von {date_diff} Tagen ist zu lang. Maximum: 366 Tage")
            
        # 5. Prüfe Datenverfügbarkeit (optional)
        try:
            cursor = self.db.conn.execute(
                "SELECT COUNT(*) FROM daily_stats WHERE deck_id = ? AND date BETWEEN ? AND ?", 
                (deck_id, start_date, end_date)
            )
            if cursor.fetchone()[0] == 0:
                validation_errors.append(f"Keine Lernstatistiken für Deck {deck_id} im angegebenen Zeitraum")
        except Exception as e:
            print(f"Study Tracker: Fehler bei der Statistik-Validierung: {e}")
        
        return validation_errors

class HeatmapWidget(QWidget):
    """
    Widget zur Anzeige der Lernstatistik als Heatmap
    
    Das Widget enthält:
    - Levelsystem mit Fortschrittsanzeige
    - Heatmap für die letzten 203 Tage (29 Wochen)
    - Statistiken zu Lernstreaks und -aktivität
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StudyTrackerWidget")
        
        # Initialisiere Datenbank
        self.db = Database()
        
        # Konstanten für die Heatmap
        self.TOTAL_WEEKS = 29  # 203 Tage / 7 = 29 Wochen
        self.ROWS = self.TOTAL_WEEKS
        self.COLS = 7  # Wochentage
        self.AUTO_SCROLL_ROW = self.ROWS - 3  # Drittletzte Zeile
        self.cell_size = 12
        
        # Deck-Auswahl und ID
        self.saved_deck = self.db.get_selected_deck()
        self.selected_deck = None if self.saved_deck == "Alle Stapel" else self.saved_deck
        self.deck_id = 0  # Standardwert auf 0 setzen statt None
        
        # Initialisiere Deck-ID
        if self.selected_deck and mw and mw.col:
            try:
                deck = mw.col.decks.by_name(self.selected_deck)
                if deck:
                    self.deck_id = deck['id']
            except Exception as e:
                print(f"Fehler beim Abrufen des Decks: {e}")
        
        # Initialisiere Level-System
        self.level_system = LevelSystem(self.db, self.deck_id)
        
        # Setze Startdatum für die Heatmap
        self.today = datetime.now().date()
        offset_to_monday = self.today.weekday()
        self.start_date = self.today - timedelta(days=203 + offset_to_monday)
        
        # Hole Installationsdatum
        installation_date_str = self.db.get_setting('installation_date')
        if installation_date_str:
            try:
                self.installation_date = datetime.strptime(installation_date_str, "%Y-%m-%d").date()
            except ValueError:
                self.installation_date = self.today - timedelta(days=30)  # Fallback
        else:
            # Setze und speichere Installationsdatum
            self.installation_date = self.today
            self.db.save_setting('installation_date', self.today.strftime("%Y-%m-%d"))
        
        # Display-Konfiguration basierend auf Bildschirmgröße
        screen = QApplication.primaryScreen()
        screen_width = screen.size().width()
        self.show_stats = screen_width > MOBILE_SCREEN_WIDTH
        
        # UI einrichten
        self.setup_ui()
        
        # Importiere historische Daten aus AnkiWeb und aktualisiere Statistiken
        self.import_ankiweb_data()
        self.update_stats_and_heatmap()
        
        # Widget sichtbar machen
        self.setVisible(True)
        print("Study Tracker: Widget erfolgreich initialisiert")
    
    def setup_ui(self):
        """Richtet die Benutzeroberfläche des Widgets ein"""
        print("Study Tracker: Richte UI ein...")
        
        # Setze Widget-Größe
        self.setFixedWidth(200)
        self.setFixedHeight(550)
        
        # Haupt-Layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # Button-Container
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setSpacing(3)
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        # Bericht-Button
        report_btn = QPushButton("Bericht")
        report_btn.setFixedSize(90, 22)
        report_btn.clicked.connect(self.show_report_dialog)
        
        # Deck-Button
        deck_btn = QPushButton("Stapel")
        deck_btn.setFixedSize(90, 22)
        deck_btn.clicked.connect(self.show_deck_selector)
        
        button_layout.addWidget(report_btn)
        button_layout.addWidget(deck_btn)
        main_layout.addWidget(button_container)
        
        # Level und Fortschritt
        level_container = QWidget()
        level_layout = QVBoxLayout(level_container)
        level_layout.setContentsMargins(0, 0, 0, 0)
        level_layout.setSpacing(2)
        
        # Level-Label
        self.level_label = QLabel(f"Level {self.level_system.current_level}")
        self.level_label.setObjectName("levelLabel")
        self.level_label.setStyleSheet("font-weight: bold; color: #388e3c;")
        level_layout.addWidget(self.level_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Fortschrittsbalken
        self.week_progress_bar = QProgressBar()
        self.week_progress_bar.setFixedHeight(5)
        self.week_progress_bar.setTextVisible(False)
        level_layout.addWidget(self.week_progress_bar)
        
        main_layout.addWidget(level_container)
        
        # Heatmap-Bereich
        heatmap_container = QWidget()
        heatmap_layout = QVBoxLayout(heatmap_container)
        heatmap_layout.setContentsMargins(0, 5, 0, 5)
        heatmap_layout.setSpacing(2)
        
        # Wochentagsanzeige
        days_container = QWidget()
        days_layout = QHBoxLayout(days_container)
        days_layout.setSpacing(4)
        days_layout.setContentsMargins(0, 0, 0, 0)
        
        # Wochentagslabels
        for day in ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]:
            label = QLabel(day)
            label.setAlignment(get_qt_enum(Qt.AlignmentFlag, "AlignCenter"))
            label.setStyleSheet("font-size: 10px; color: #666666;")
            label.setFixedWidth(12)
            days_layout.addWidget(label)
        
        heatmap_layout.addWidget(days_container)
        
        # Grid für die Heatmap
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setHorizontalSpacing(4)
        self.grid_layout.setVerticalSpacing(4)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        heatmap_layout.addWidget(self.grid_widget)
        
        main_layout.addWidget(heatmap_container)
        
        # Stats Container (nur auf größeren Bildschirmen)
        if self.show_stats:
            stats_container = QWidget()
            stats_layout = QVBoxLayout(stats_container)
            stats_layout.setSpacing(2)
            stats_layout.setContentsMargins(0, 5, 0, 0)
            
            self.stats_labels = {}
            for stat_name in ['days_learned', 'longest_streak', 'current_streak']:
                label = QLabel()
                label.setWordWrap(True)
                label.setStyleSheet("font-size: 12px;")
                stats_layout.addWidget(label)
                self.stats_labels[stat_name] = label
            
            # Aktualisieren-Button
            refresh_btn = QPushButton("Aktualisieren")
            refresh_btn.clicked.connect(self.force_refresh)
            stats_layout.addWidget(refresh_btn)
            
            main_layout.addWidget(stats_container)
        
        # Füge Abstand unten hinzu
        main_layout.addStretch()
        
        # Erstelle die Heatmap
        self.create_heatmap()
    
    def create_heatmap(self):
        """Erstellt die Heatmap-Visualisierung"""
        # Entferne alte Zellen
        for i in reversed(range(self.grid_layout.count())): 
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        for row in range(self.ROWS):
            for col in range(self.COLS):
                current_date = self.start_date + timedelta(days=row * 7 + col)
                
                # Standard: Grau
                intensity = 0
                
                # Prüfe, ob das Datum nach der Installation liegt
                if current_date >= self.installation_date and current_date <= self.today:
                    intensity = self.get_day_intensity(current_date)
                
                # Markiere heutigen Tag
                is_today = current_date == self.today
                border_style = "1px solid black" if is_today else "none"
                
                # Erstelle Zelle
                cell = QFrame()
                cell.setFixedSize(self.cell_size, self.cell_size)
                cell.setObjectName("heatmapCell")
                cell.setStyleSheet(f"""
                    QFrame {{
                        background-color: {self.get_color_for_intensity(intensity)};
                        border: {border_style};
                        min-height: {self.cell_size}px;
                        max-height: {self.cell_size}px;
                        min-width: {self.cell_size}px;
                        max-width: {self.cell_size}px;
                        border-radius: 2px;
                    }}
                    QFrame:hover {{
                        border: 1px solid #000;
                    }}
                """)
                
                # Tooltip mit Details für den Tag
                if current_date >= self.installation_date:
                    stats = self.get_day_stats(current_date)
                    tooltip = (
                        f"<b>{current_date.strftime('%d.%m.%Y')}</b><br>"
                        f"Fällige Karten: {stats['cards_due']}<br>"
                        f"Gelernte Karten: {stats['cards_studied']}"
                    )
                    cell.setToolTip(tooltip)
                
                self.grid_layout.addWidget(cell, row, col)
    
    def get_day_intensity(self, date):
        """
        Bestimmt die Intensität (Farbe) eines Tages in der Heatmap
        
        Returns:
            int: 0=Grau, 1=Grün, 2=Orange, 3=Rot
        """
        stats = self.get_day_stats(date)
        cards_due = stats['cards_due']
        cards_studied = stats['cards_studied']
        
        # Wenn keine Karten fällig waren, sollte der Tag grün sein
        if cards_due == 0:
            return 1  # Grün
        # Wenn alle fälligen Karten gelernt wurden
        elif cards_studied >= cards_due:
            return 1  # Grün
        # Wenn teilweise gelernt wurde
        elif cards_studied > 0:
            return 2  # Orange
        # Wenn Karten fällig aber keine gelernt
        else:
            return 3  # Rot
    
    def get_color_for_intensity(self, intensity):
        """Liefert die Farbe für die gegebene Intensität"""
        colors = {
            0: "#e0e0e0",  # Grau (keine Daten/Zukunft)
            1: "#8dcf82",  # Grün (alle fälligen Karten gelernt)
            2: "#FFA500",  # Orange (teilweise gelernt)
            3: "#f28b82"   # Rot (keine gelernt aber fällig)
        }
        return colors.get(intensity, colors[0])
    
    def get_day_stats(self, date):
        """Holt die Statistiken für einen bestimmten Tag"""
        date_str = date.strftime("%Y-%m-%d")
        return self.db.get_daily_stats(date_str, self.deck_id)
    
    def import_ankiweb_data(self):
        """Importiert historische Daten aus AnkiWeb"""
        try:
            # Erstelle StatisticsCollector
            collector = StudyStatisticsCollector(self.db)
            
            # Importiere historische Reviewnamen
            collector.import_historical_revlog()
            
            # Parse Validierungscodes aus Karten
            collector.parse_validation_codes_from_cards()
            
            print("Study Tracker: AnkiWeb-Daten erfolgreich importiert")
        except Exception as e:
            print(f"Fehler beim Import von AnkiWeb-Daten: {e}")
            traceback.print_exc()
    
    def update_stats_and_heatmap(self):
        """Aktualisiert alle Statistiken und die Heatmap"""
        try:
            # Sammle aktuelle Statistiken
            collector = StudyStatisticsCollector(self.db)
            collector.collect_daily_stats()
            
            today = datetime.now().date()
            
            # Prüfe Auto-Scroll
            needs_update = self.check_auto_scroll(today)
            
            # Aktualisiere Heatmap wenn nötig
            if needs_update:
                self.create_heatmap()
            
            # Level-System-Updates
            result = self.level_system.check_period_completion()
            
            # Wenn eine Meldung zurückgegeben wurde, zeige sie an
            if isinstance(result, str):
                if result == "level_up":
                    self.show_level_up_animation()
                else:
                    self.show_status_message(result)
            
            # Aktualisiere Level und Fortschritt
            self.level_label.setText(f"Level {self.level_system.current_level}")
            progress = self.level_system.calculate_progress_percent()
            self.week_progress_bar.setValue(int(progress))
            
            # Aktualisiere Statistik-Labels
            if self.show_stats:
                stats = self.calculate_stats()
                self.update_stats(stats)
            
            print("Study Tracker: Statistiken aktualisiert")
        except Exception as e:
            print(f"Fehler bei der Aktualisierung der Statistiken: {e}")
            traceback.print_exc()
    
    def check_auto_scroll(self, current_date):
        """
        Prüft und führt Auto-Scroll der Heatmap durch, wenn nötig
        
        Returns:
            bool: True wenn ein Update nötig ist, sonst False
        """
        needs_update = False
        while (current_date - self.start_date).days // 7 >= self.AUTO_SCROLL_ROW:
            self.start_date += timedelta(days=7)
            needs_update = True
        return needs_update
    
    def calculate_stats(self):
        """
        Berechnet die Statistiken für das Widget
        
        Returns:
            dict: Statistiken (days_learned, longest_streak, current_streak)
        """
        streak_calc = StreakCalculator(self.db, self.deck_id)
        
        days_learned = round(streak_calc.calculate_days_learned_percent())
        longest_streak = streak_calc.calculate_longest_streak()
        current_streak = streak_calc.calculate_current_streak()
        
        return {
            'days_learned': days_learned,
            'longest_streak': longest_streak,
            'current_streak': current_streak
        }
    
    def update_stats(self, stats):
        """Aktualisiert die Statistik-Labels im Widget"""
        if not self.show_stats:
            return
        
        self.stats_labels['days_learned'].setText(f"Gelernt an: {stats['days_learned']}% der Tage")
        self.stats_labels['longest_streak'].setText(f"Längste Serie: {stats['longest_streak']} Tage")
        self.stats_labels['current_streak'].setText(f"Aktuelle Serie: {stats['current_streak']} Tage")
        
        # Prüfe auf neuen Streak-Rekord
        if stats['current_streak'] > 0:
            is_new_record = self.db.save_streak_record(self.deck_id, stats['current_streak'])
            if is_new_record:
                self.show_streak_record_animation(stats['current_streak'])
    
    def show_streak_record_animation(self, new_record):
        """Zeigt eine Animation für einen neuen Streak-Rekord"""
        animation_widget = QWidget(self)
        animation_widget.setStyleSheet("""
            background: linear-gradient(45deg, #FF6600, #FF8533);
            border-radius: 15px;
            padding: 15px;
            box-shadow: 2px 2px 10px rgba(0, 0, 0, 0.2);
        """)
        
        layout = QVBoxLayout(animation_widget)
        layout.setSpacing(8)
        
        emoji_label = QLabel("🔥")
        emoji_label.setStyleSheet("font-size: 24px;")
        
        text_label = QLabel(f"Neuer Rekord!")
        text_label.setStyleSheet("""
            color: white;
            font-size: 16px;
            font-weight: bold;
        """)
        
        days_label = QLabel(f"{new_record} Tage!")
        days_label.setStyleSheet("""
            color: white;
            font-size: 15px;
        """)
        
        layout.addWidget(emoji_label, alignment=get_qt_enum(Qt.AlignmentFlag, "AlignCenter"))
        layout.addWidget(text_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(days_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        animation_widget.setFixedSize(180, 100)
        animation_widget.move(self.width(), 10)
        animation_widget.show()
        
        # Einblenden
        slide_in = QPropertyAnimation(animation_widget, b"pos")
        slide_in.setDuration(800)
        slide_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        end_x = self.width() - animation_widget.width() - 20
        
        slide_in.setStartValue(QPoint(self.width(), 10))
        slide_in.setEndValue(QPoint(end_x, 10))
        
        # Ausblenden
        slide_out = QPropertyAnimation(animation_widget, b"pos")
        slide_out.setDuration(800)
        slide_out.setEasingCurve(QEasingCurve.Type.InCubic)
        slide_out.setStartValue(QPoint(end_x, 10))
        slide_out.setEndValue(QPoint(self.width(), 10))
        
        slide_out.finished.connect(animation_widget.deleteLater)
        
        slide_in.start()
        
        # Nach 2,5 Sekunden ausblenden
        QTimer.singleShot(2500, slide_out.start)
    
    def show_level_up_animation(self):
        """Zeigt eine Animation für ein Level-Up"""
        QMessageBox.information(
            self,
            "Level Up!",
            f"Glückwunsch! Du hast Level {self.level_system.current_level} erreicht! 🎉"
        )
    
    def show_status_message(self, message):
        """Zeigt eine Statusnachricht an"""
        QMessageBox.information(self, "Status Update", message)
    
    def show_deck_selector(self):
        """Zeigt den Dialog zur Deck-Auswahl"""
        dialog = DeckSelectorDialog(self, self.selected_deck)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = dialog.deck_list.currentItem().text()
            self.selected_deck = None if selected == "Alle Stapel" else selected
            
            # Aktualisiere deck_id
            self.deck_id = None
            if self.selected_deck and mw and mw.col:
                deck = mw.col.decks.by_name(self.selected_deck)
                if deck:
                    self.deck_id = deck['id']
            
            # Speichere Auswahl
            self.db.save_selected_deck(selected)
            
            # Reinitialisiere Level-System mit neuer deck_id
            self.level_system = LevelSystem(self.db, self.deck_id)
            
            # Aktualisiere Anzeige
            self.update_stats_and_heatmap()
    
    def show_report_dialog(self):
        """Zeigt den Dialog zur Berichtserstellung an"""
        if not self.deck_id:
            QMessageBox.warning(
                self,
                "Kein Deck ausgewählt",
                "Bitte wählen Sie zuerst ein Deck aus, für das ein Bericht erstellt werden soll."
            )
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Berichtszeitraum auswählen")
        dialog.setStyleSheet("QWidget { background-color: #f9f9f9; }")
        
        layout = QVBoxLayout(dialog)
        date_layout = QGridLayout()
        
        # Datumsauswahl
        start_date = QDateEdit()
        start_date.setDate(QDate.currentDate().addDays(-30))
        end_date = QDateEdit()
        end_date.setDate(QDate.currentDate())
        
        date_layout.addWidget(QLabel("Von:"), 0, 0)
        date_layout.addWidget(start_date, 0, 1)
        date_layout.addWidget(QLabel("Bis:"), 1, 0)
        date_layout.addWidget(end_date, 1, 1)
        
        layout.addLayout(date_layout)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(
            lambda: self.export_report(
                start_date.date().toString("yyyy-MM-dd"),
                end_date.date().toString("yyyy-MM-dd")
            )
        )
        buttons.rejected.connect(dialog.reject)
        
        layout.addWidget(buttons)
        dialog.exec()
    
    def export_report(self, start_date, end_date):
        """Exportiert den Bericht für den gewählten Zeitraum mit direkter Datenbankabfrage"""
        if not self.deck_id:
            QMessageBox.warning(
                self,
                "Kein Deck ausgewählt",
                "Bitte wählen Sie zuerst ein Deck aus, für das ein Bericht erstellt werden soll."
            )
            return
        
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Bericht speichern",
            "",
            "HTML Dateien (*.html);;Alle Dateien (*.*)"
        )
        
        if file_name:
            try:
                # Zeige Fortschrittsdialog
                progress = QProgressDialog("Bereite Bericht vor...", "Abbrechen", 0, 100, self)
                progress.setWindowTitle("Study Tracker")
                progress.setWindowModality(get_qt_enum(Qt.WindowModality, "WindowModal"))
                progress.setValue(0)
                progress.show()
                QApplication.processEvents()
                
                # Prüfe Datenbankintegrität vor Berichtserstellung
                progress.setValue(5)
                progress.setLabelText("Prüfe Datenbank...")
                QApplication.processEvents()
                
                self.db.repair_database_if_needed()
                
                # Erzeuge Bericht mit direkter Datenbankabfrage
                progress.setValue(10)
                progress.setLabelText("Generiere Bericht...")
                QApplication.processEvents()
                
                report_generator = ReportGenerator(self.db)
                html_content = report_generator.generate_report_with_direct_data(
                    self.deck_id,
                    start_date,
                    end_date
                )
                
                # Speichere Bericht
                progress.setValue(90)
                progress.setLabelText("Speichere Bericht...")
                QApplication.processEvents()
                
                with open(file_name, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                
                progress.setValue(100)
                progress.close()
                
                QMessageBox.information(
                    self,
                    "Erfolg",
                    f"Bericht wurde erfolgreich gespeichert unter:\n{file_name}"
                )
            except Exception as e:
                if 'progress' in locals():
                    progress.close()
                    
                QMessageBox.critical(
                    self,
                    "Fehler",
                    f"Fehler beim Speichern des Berichts:\n{str(e)}"
                )
    
    def show_backup_dialog(self):
        """Dialog für Backup-Verwaltung"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Datenübertragung")
        layout = QVBoxLayout(dialog)

        # Export-Button
        export_btn = QPushButton("Daten exportieren")
        export_btn.clicked.connect(self.create_backup)
        layout.addWidget(export_btn)
        
        # Import-Button
        import_btn = QPushButton("Daten importieren")
        import_btn.clicked.connect(self.import_backup)
        layout.addWidget(import_btn)
        
        dialog.exec()
    
    def create_backup(self):
        """Erstellt ein Backup der Daten"""
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Daten exportieren",
            "",
            "Study Tracker Daten (*.db);;Alle Dateien (*.*)"
        )
        
        if file_name:
            password, ok = QInputDialog.getText(
                self,
                "Passwortschutz",
                "Optional: Passwort für Verschlüsselung (leer lassen für unverschlüsseltes Backup):",
                QLineEdit.EchoMode.Password
            )
            
            if ok:  # User clicked OK
                if self.db.export_backup(file_name, password if password else None):
                    QMessageBox.information(
                        self,
                        "Erfolg",
                        "Daten wurden erfolgreich exportiert." +
                        ("\nBitte merken Sie sich das Passwort!" if password else "")
                    )
                else:
                    QMessageBox.critical(
                        self,
                        "Fehler",
                        "Daten konnten nicht exportiert werden."
                    )
    
    def import_backup(self):
        """Importiert ein Backup"""
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Warnung")
        msg.setText("Beim Import werden alle aktuellen Daten überschrieben!")
        msg.setInformativeText("Möchten Sie fortfahren?")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if msg.exec() == QMessageBox.StandardButton.Yes:
            file_name, _ = QFileDialog.getOpenFileName(
                self,
                "Daten importieren",
                "",
                "Study Tracker Daten (*.db);;Alle Dateien (*.*)"
            )
            
            if file_name:
                password, ok = QInputDialog.getText(
                    self,
                    "Passwortschutz",
                    "Falls die Datei verschlüsselt ist, geben Sie das Passwort ein:",
                    QLineEdit.EchoMode.Password
                )
                
                if ok:  # User clicked OK
                    if self.db.import_backup(file_name, password if password else None):
                        QMessageBox.information(
                            self,
                            "Erfolg",
                            "Daten wurden erfolgreich importiert."
                        )
                        # Aktualisiere Anzeige
                        self.level_system = LevelSystem(self.db, self.deck_id)
                        self.update_stats_and_heatmap()
                    else:
                        QMessageBox.critical(
                            self,
                            "Fehler",
                            "Daten konnten nicht importiert werden.\nFalsches Passwort?"
                        )
    
    def force_refresh(self):
        """Erzwingt eine komplette Aktualisierung aller Statistiken und Daten"""
        print("Study Tracker: Erzwinge komplette Aktualisierung")
        
        # Zeige Fortschrittsanzeige - PyQt6 kompatibel
        progress = QProgressDialog("Aktualisiere Study Tracker Daten...", "Abbrechen", 0, 7, self)
        progress.setWindowTitle("Study Tracker")
        
        # Fix for PyQt6 compatibility
        try:
            # For PyQt6
            progress.setWindowModality(get_qt_enum(Qt.WindowModality, "WindowModal"))
        except AttributeError:
            try:
                # For PyQt5
                progress.setWindowModality(get_qt_enum(Qt.WindowModality, "WindowModal"))
            except AttributeError:
                # Fallback if neither works
                print("Study Tracker: Konnte WindowModality nicht setzen, fahre ohne fort")
        
        progress.show()
        
        try:
            # Sammle aktuelle Statistiken
            collector = StudyStatisticsCollector(self.db)
            
            # 1. Tägliche Statistiken aktualisieren
            progress.setValue(1)
            progress.setLabelText("Aktualisiere tägliche Statistiken...")
            QApplication.processEvents()
            
            print("Study Tracker: Aktualisiere tägliche Statistiken...")
            collector.collect_daily_stats()
            
            # 2. Historische Daten importieren mit verbesserter Fehlerbehandlung
            progress.setValue(2)
            progress.setLabelText("Importiere historische Reviewnamen...")
            QApplication.processEvents()
            
            try:
                print("Study Tracker: Importiere historische Reviewnamen...")
                collector.import_historical_revlog()
            except Exception as e:
                print(f"Study Tracker: Fehler beim Import historischer Reviewnamen: {e}")
                traceback.print_exc()
            
            # 3. Validierungscodes mit verbesserter Methode parsen
            progress.setValue(3)
            progress.setLabelText("Aktualisiere Validierungscodes und ChatGPT-Links...")
            QApplication.processEvents()
            
            try:
                print("Study Tracker: Aktualisiere Validierungscodes und ChatGPT-Links...")
                collector.parse_validation_codes_from_cards()
            except Exception as e:
                print(f"Study Tracker: Fehler beim Parsen der Validierungscodes: {e}")
                traceback.print_exc()
            
            # 4. ChatGPT-Links mit Validierungscodes verknüpfen
            progress.setValue(4)
            progress.setLabelText("Verknüpfe ChatGPT-Links mit Validierungscodes...")
            QApplication.processEvents()
            
            try:
                print("Study Tracker: Verknüpfe ChatGPT-Links mit Validierungscodes...")
                collector.link_chat_links_with_validation_codes()
            except Exception as e:
                print(f"Study Tracker: Fehler beim Verknüpfen von ChatGPT-Links: {e}")
                traceback.print_exc()
            
            # 5. Level-System für ALLE Decks aktualisieren - VERBESSERT
            progress.setValue(5)
            progress.setLabelText("Aktualisiere Level-System für ALLE Decks...")
            QApplication.processEvents()
            
            try:
                print("Study Tracker: Aktualisiere Level-System für ALLE Decks...")
                # Übergebe None, um alle Decks zu aktualisieren
                collector.initialize_level_system(None)
                
                # Hole Liste aller Decks mit ihrem aktuellen Level
                if mw and mw.col:
                    decks = mw.col.decks.all()
                    print("Study Tracker: Aktuelle Level-Informationen:")
                    for deck in decks:
                        # Überspringe Standard-Deck
                        if deck['id'] == 1:
                            continue
                        
                        try:
                            level_data = self.db.get_level_progress(deck['id'])
                            if level_data:
                                print(f"  - Deck {deck['name']}: Level {level_data['level']}")
                            else:
                                print(f"  - Deck {deck['name']}: Kein Level-Fortschritt gefunden")
                        except Exception as e:
                            print(f"  - Fehler beim Abrufen des Level-Fortschritts für Deck {deck['name']}: {e}")
            except Exception as e:
                print(f"Study Tracker: Fehler bei der Aktualisierung des Level-Systems: {e}")
                traceback.print_exc()
            
            # NEU: Synchronisiere Karten mit aktuellen Stapeln
            progress.setValue(5.5)
            progress.setLabelText("Synchronisiere Karten mit aktuellen Stapeln...")
            QApplication.processEvents()

            try:
                print("Study Tracker: Synchronisiere Karten mit aktuellen Stapeln...")
                self.db.efficient_card_tracking()
                self.db.update_all_validation_code_links()
            except Exception as e:
                print(f"Study Tracker: Fehler bei der Kartensynchronisierung: {e}")
                traceback.print_exc()

            # 6. Fehlerhafte Level-Datensätze bereinigen
            progress.setValue(6)
            progress.setLabelText("Bereinige fehlerhafte Level-Datensätze...")
            QApplication.processEvents()
            
            try:
                print("Study Tracker: Bereinige fehlerhafte Level-Datensätze...")
                deleted_count = self.db.clean_duplicate_level_entries()
                print(f"Study Tracker: {deleted_count} doppelte Level-Einträge bereinigt")
            except Exception as e:
                print(f"Study Tracker: Fehler bei der Bereinigung fehlerhafter Level-Datensätze: {e}")
                traceback.print_exc()
            
            # 7. Aktualisiere Anzeige
            progress.setValue(7)
            progress.setLabelText("Aktualisiere Anzeige...")
            QApplication.processEvents()
            
            print("Study Tracker: Aktualisiere Anzeige...")
            self.create_heatmap()
            
            # Reinitialisiere Level-System für das aktuell gewählte Deck
            self.level_system = LevelSystem(self.db, self.deck_id)
            self.update_stats_and_heatmap()
            
            # Zeige die Anzahl der geladenen Daten zur Bestätigung
            try:
                cursor = self.db.conn.execute("SELECT COUNT(*) FROM validation_codes")
                validation_count = cursor.fetchone()[0]
                
                cursor = self.db.conn.execute("SELECT COUNT(*) FROM chat_links")
                chatlink_count = cursor.fetchone()[0]
                
                cursor = self.db.conn.execute("SELECT COUNT(*) FROM level_history")
                level_count = cursor.fetchone()[0]
                
                print(f"Study Tracker: Aktualisierung abgeschlossen:")
                print(f"  - Validierungscodes: {validation_count}")
                print(f"  - ChatGPT-Links: {chatlink_count}")
                print(f"  - Level-Historieneinträge: {level_count}")
                
                # Zeige Erfolgsmeldung
                QMessageBox.information(
                    self,
                    "Study Tracker",
                    f"Aktualisierung abgeschlossen:\n\n"
                    f"Validierungscodes: {validation_count}\n"
                    f"ChatGPT-Links: {chatlink_count}\n"
                    f"Level-Historieneinträge: {level_count}"
                )
            except Exception as e:
                print(f"Study Tracker: Fehler beim Abrufen der Datenbankstatistik: {e}")
            
        except Exception as e:
            print(f"Study Tracker: Fehler bei der kompletten Aktualisierung: {e}")
            traceback.print_exc()
            
            QMessageBox.warning(
                self,
                "Study Tracker",
                f"Fehler bei der Aktualisierung: {str(e)}\n\n"
                f"Bitte überprüfen Sie die Anki-Konsole für weitere Details."
            )
        finally:
            # Schließe Fortschrittsanzeige
            progress.close()
            
            # Verarbeite ausstehende UI-Events
            QApplication.processEvents()
            
            print("Study Tracker: Komplette Aktualisierung abgeschlossen")
    
    def closeEvent(self, event):
        """Event beim Schließen des Widgets"""
        # Speichere Statistiken vor dem Schließen
        collector = StudyStatisticsCollector(self.db)
        collector.collect_daily_stats()
        
        # Schließe Datenbankverbindung
        self.db.close()
        
        # Standardverhalten
        super().closeEvent(event)


class DeckSelectorDialog(QDialog):
    """Dialog zur Deck-Auswahl"""
    
    def __init__(self, parent=None, selected_deck=None):
        super().__init__(parent)
        self.setWindowTitle("Stapel auswählen")
        self.setStyleSheet("background-color: #f9f9f9;")

        layout = QVBoxLayout(self)
        
        # Decklist
        self.deck_list = QListWidget()
        self.deck_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            QListWidget::item {
                padding: 8px;
            }
            QListWidget::item:selected {
                background-color: #e0e0e0;
            }
        """)
        
        # Füge "Alle Stapel" hinzu
        self.deck_list.addItem("Alle Stapel")
        
        # Füge alle Decks hinzu
        if mw and mw.col:
            for deck in mw.col.decks.all():
                # Überspringe Standarddeck
                if deck['id'] == 1:
                    continue
                self.deck_list.addItem(deck['name'])
        
        # Setze Auswahl
        if selected_deck:
            items = self.deck_list.findItems(selected_deck, get_qt_enum(Qt.MatchFlag, "MatchExactly"))
            if items:
                items[0].setSelected(True)
                self.deck_list.setCurrentItem(items[0])
        else:
            self.deck_list.item(0).setSelected(True)
            self.deck_list.setCurrentItem(self.deck_list.item(0))
        
        layout.addWidget(self.deck_list)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def initialize_addon():
    """Initializes the add-on with improved data processing and maintenance"""
    print("Study Tracker: Starting initialization...")
    
    # Check for Anki readiness
    if not mw or not mw.col:
        print("Study Tracker: Anki not ready, initialization postponed...")
        QTimer.singleShot(1000, initialize_addon)
        return
    
    try:
        # Initialize database
        db = Database()
        
        # Schedule periodic validation code cleanup (every 14 days by default)
        schedule_periodic_cleanup(interval_days=14)
        
        # Clean up duplicate level entries
        deleted_count = db.clean_duplicate_level_entries()
        print(f"Study Tracker: {deleted_count} duplicate level entries cleaned up")
        
        # Check for database errors
        if db.last_error:
            print(f"Study Tracker: Database initialization failed: {db.last_error}")
            QMessageBox.critical(
                mw,
                "Study Tracker Error",
                f"An error occurred during database initialization:\n\n{db.last_error}\n\n"
                f"Please check the Anki console for more details."
            )
            return
        
        # Set or update installation date
        installation_date = db.get_setting('installation_date')
        if not installation_date:
            today = datetime.now().strftime("%Y-%m-%d")
            db.save_setting('installation_date', today)
            print(f"Study Tracker: Installation date set to {today}")
        
        # Create statistics collector for data import
        collector = StudyStatisticsCollector(db)
        
        # Import historical data from Anki
        print("Study Tracker: Importing historical data...")
        collector.import_historical_revlog()
        
        # Parse validation codes using our unified function
        print("Study Tracker: Importing validation codes and ChatGPT links...")
        collector.parse_validation_codes_from_cards()
        
        # Link ChatGPT links with validation codes
        collector.link_chat_links_with_validation_codes()
        
        # Initialize level system for ALL decks
        print("Study Tracker: Initializing level system for all decks...")
        collector.initialize_level_system(None)  # Pass None to initialize all decks
        
        # Show database statistics
        try:
            cursor = db.conn.execute("SELECT COUNT(*) FROM validation_codes")
            validation_count = cursor.fetchone()[0]
            
            cursor = db.conn.execute("SELECT COUNT(*) FROM chat_links")
            chatlink_count = cursor.fetchone()[0]
            
            cursor = db.conn.execute("SELECT COUNT(*) FROM level_history")
            level_count = cursor.fetchone()[0]
            
            print(f"Study Tracker: Database statistics after initialization:")
            print(f"  - Validation codes: {validation_count}")
            print(f"  - ChatGPT links: {chatlink_count}")
            print(f"  - Level history entries: {level_count}")
        except Exception as e:
            print(f"Study Tracker: Error retrieving database statistics: {e}")
        
        # Create widget and dock
        success = create_widget()
        
        if not success:
            print("Study Tracker: Widget creation failed")
            QMessageBox.warning(
                mw,
                "Study Tracker Warning",
                "The Study Tracker widget could not be created. Please restart Anki and try again."
            )
            return
        
        # Check for updates
        check_updates()
        
        print("Study Tracker: Initialization completed")
    except Exception as e:
        print(f"Study Tracker: Error during initialization: {e}")
        traceback.print_exc()
        
        QMessageBox.critical(
            mw,
            "Study Tracker Error",
            f"An error occurred during initialization:\n\n{str(e)}\n\n"
            f"Please check the Anki console for more details."
        )
    finally:
        # Close database connection
        if 'db' in locals():
            db.close()

def test_validation_code_formats():
    """
    Testet die Erkennung verschiedener Validierungscode-Formate
    Hilfreich zur Diagnose von Format-Problemen
    """
    
    test_strings = [
        "2025-02-20: 4001",
        "2025-02-20:4001",
        "2025-02-20 4001",
        "2025.02.20: 4001",
        "2025.02.20:4001",
        "2025.02.20 4001",
        "Ungültiges Format",
        "20.02.2025: 4001"  # Nicht unterstütztes Format
    ]
    
    # Erweiterte Regex für verschiedene Formate
    regex = r'(\d{4}[-\.]\d{2}[-\.]\d{2})(?:[:]\s*|\s+)(\d{4})'
    
    print("Study Tracker: Test der Validierungscode-Formate:")
    for test_str in test_strings:
        match = re.match(regex, test_str)
        if match:
            date, code = match.groups()
            print(f"  ✓ '{test_str}' -> Datum: '{date}', Code: '{code}'")
        else:
            print(f"  ✗ '{test_str}' -> Kein Match")
    
    return True


# Funktion zum Testen der Kartenfeld-Extraktion
def test_card_field_access():
    """
    Testet den Zugriff auf die Kartenfelder 'ValidierungscodesListe' und 'ChatGPT-Link'
    Nützlich zur Diagnose von Problemen mit der Feldextraktion
    """
    if not mw or not mw.col:
        print("Study Tracker: Anki nicht bereit")
        return False
    
    try:
        # Hole alle Notizen mit dem Feld 'ValidierungscodesListe'
        note_ids_validation = mw.col.find_notes("ValidierungscodesListe:*")
        print(f"Study Tracker: Gefunden: {len(note_ids_validation)} Notizen mit ValidierungscodesListe")
        
        # Hole alle Notizen mit dem Feld 'ChatGPT-Link'
        note_ids_chatgpt = mw.col.find_notes("ChatGPT-Link:*")
        print(f"Study Tracker: Gefunden: {len(note_ids_chatgpt)} Notizen mit ChatGPT-Link")
        
        # Überprüfe die ersten 5 Notizen mit ValidierungscodesListe
        if note_ids_validation:
            print("\nStudy Tracker: Beispiel-ValidierungscodesListen:")
            for i, note_id in enumerate(note_ids_validation[:5]):
                try:
                    note = mw.col.get_note(note_id)
                    content = note.get('ValidierungscodesListe', '').strip()
                    print(f"  Notiz {i+1}: {content[:100]}{'...' if len(content) > 100 else ''}")
                except Exception as e:
                    print(f"  Fehler beim Zugriff auf Notiz {note_id}: {e}")
        
        # Überprüfe die ersten 5 Notizen mit ChatGPT-Link
        if note_ids_chatgpt:
            print("\nStudy Tracker: Beispiel-ChatGPT-Links:")
            for i, note_id in enumerate(note_ids_chatgpt[:5]):
                try:
                    note = mw.col.get_note(note_id)
                    content = note.get('ChatGPT-Link', '').strip()
                    print(f"  Notiz {i+1}: {content[:100]}{'...' if len(content) > 100 else ''}")
                except Exception as e:
                    print(f"  Fehler beim Zugriff auf Notiz {note_id}: {e}")
        
        return True
    except Exception as e:
        print(f"Study Tracker: Fehler beim Testen des Kartenfeld-Zugriffs: {e}")
        traceback.print_exc()
        return False

# Diese Funktion zur Diagnose im Fehlerfall aufrufen
def diagnose_validation_code_problems():
    """
    Umfassende Diagnose für Probleme mit Validierungscodes und ChatGPT-Links
    """
    print("\n===== Study Tracker: Diagnose gestartet =====")
    
    # Teste Kartenfeld-Zugriff
    print("\n--- Teste Kartenfeld-Zugriff ---")
    test_card_field_access()
    
    # Teste Validierungscode-Formate
    print("\n--- Teste Validierungscode-Formate ---")
    test_validation_code_formats()
    
    # Teste Datenbankzugriff
    print("\n--- Teste Datenbankzugriff ---")
    try:
        db = Database()
        
        # Überprüfe Tabellen
        cursor = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"Vorhandene Tabellen: {[t[0] for t in tables]}")
        
        # Überprüfe Anzahl der Validierungscodes
        cursor = db.conn.execute("SELECT COUNT(*) FROM validation_codes")
        validation_count = cursor.fetchone()[0]
        print(f"Validierungscodes in Datenbank: {validation_count}")
        
        # Überprüfe Anzahl der ChatGPT-Links
        cursor = db.conn.execute("SELECT COUNT(*) FROM chat_links")
        chatlink_count = cursor.fetchone()[0]
        print(f"ChatGPT-Links in Datenbank: {chatlink_count}")
        
        # Überprüfe Beispiel-Validierungscodes
        if validation_count > 0:
            cursor = db.conn.execute("SELECT * FROM validation_codes LIMIT 5")
            codes = cursor.fetchall()
            print("\nBeispiel-Validierungscodes:")
            for code in codes:
                print(f"  {code}")
        
        # Überprüfe Beispiel-ChatGPT-Links
        if chatlink_count > 0:
            cursor = db.conn.execute("SELECT * FROM chat_links LIMIT 5")
            links = cursor.fetchall()
            print("\nBeispiel-ChatGPT-Links:")
            for link in links:
                print(f"  {link}")
        
        db.close()
    except Exception as e:
        print(f"Fehler beim Testen des Datenbankzugriffs: {e}")
        traceback.print_exc()
    
    print("\n===== Study Tracker: Diagnose abgeschlossen =====")

# Funktion zum manuellen Aktualisieren der Validierungscodes 
# (kann über ein Menü im Anki-Interface aufgerufen werden)
def force_update_validation_codes():
    """
    Erzwingt eine Aktualisierung aller Validierungscodes aus den Karten
    mit verbesserter Fehlerbehandlung und Feedback
    """
    try:
        # Initialisiere Datenbank
        db = Database()
        
        # Erstelle Statistik-Collector
        collector = StudyStatisticsCollector(db)
        
        # Parse Validierungscodes aus Karten mit der verbesserten Methode
        print("Study Tracker: Aktualisiere Validierungscodes und ChatGPT-Links...")
        success = collector.parse_validation_codes_from_cards()
        
        # Zeige Datenbankstatistiken
        try:
            cursor = db.conn.execute("SELECT COUNT(*) FROM validation_codes")
            validation_count = cursor.fetchone()[0]
            
            cursor = db.conn.execute("SELECT COUNT(*) FROM chat_links")
            chatlink_count = cursor.fetchone()[0]
            
            print(f"Study Tracker: Datenbankstatistik nach Aktualisierung:")
            print(f"  - Validierungscodes: {validation_count}")
            print(f"  - ChatGPT-Links: {chatlink_count}")
        except Exception as e:
            print(f"Study Tracker: Fehler beim Abrufen der Datenbankstatistik: {e}")
        
        if success:
            QMessageBox.information(
                mw,
                "Study Tracker",
                f"Validierungscodes und ChatGPT-Links wurden erfolgreich aktualisiert.\n\n"
                f"Validierungscodes in Datenbank: {validation_count}\n"
                f"ChatGPT-Links in Datenbank: {chatlink_count}"
            )
        else:
            QMessageBox.warning(
                mw,
                "Study Tracker",
                "Bei der Aktualisierung der Validierungscodes ist ein Fehler aufgetreten. "
                "Bitte überprüfen Sie die Anki-Konsole für Details."
            )
    except Exception as e:
        print(f"Study Tracker: Fehler bei der Aktualisierung der Validierungscodes: {e}")
        traceback.print_exc()
        QMessageBox.critical(
            mw,
            "Study Tracker Fehler",
            f"Bei der Aktualisierung der Validierungscodes ist ein Fehler aufgetreten:\n\n{str(e)}\n\n"
            f"Bitte überprüfen Sie die Anki-Konsole für weitere Details."
        )
    finally:
        # Schließe Datenbankverbindung
        if 'db' in locals():
            db.close()

def create_widget():
    """Erstellt das Hauptwidget und das Dock"""
    try:
        if not mw or not mw.col:
            print("Study Tracker: Anki nicht bereit")
            return False
            
        if hasattr(mw, 'study_tracker_widget'):
            print("Study Tracker: Widget existiert bereits")
            return True
            
        print("Study Tracker: Erstelle Widget...")
        
        # Erstelle das Widget
        widget = HeatmapWidget()
        
        # Erstelle das Dock Widget
        dock = QDockWidget("Study Tracker", mw)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock.setWidget(widget)
        dock.setFloating(False)  # Widget soll nicht frei schweben
        
        # Füge das Dock Widget zum Hauptfenster hinzu
        mw.addDockWidget(get_qt_enum(Qt.DockWidgetArea, "RightDockWidgetArea"), dock)
        
        # Stelle sicher, dass das Dock Widget sichtbar ist
        dock.setVisible(True)
        widget.setVisible(True)
        
        # Platziere das Widget am rechten Rand
        mw.resizeDocks([dock], [200], get_qt_enum(Qt.Orientation, "Horizontal"))
        
        # Speichere Referenzen
        mw.study_tracker_widget = widget
        mw.study_tracker_dock = dock
        
        # Füge Menüeinträge hinzu
        menu = QMenu('Study Tracker', mw)
        mw.form.menubar.addMenu(menu)
        
        # Sichtbarkeit Toggle
        toggle_action = QAction('Study Tracker anzeigen', mw)
        toggle_action.setCheckable(True)
        toggle_action.setChecked(True)
        toggle_action.triggered.connect(lambda checked: dock.setVisible(checked))
        menu.addAction(toggle_action)
        
        # Trennlinie
        menu.addSeparator()
        
        # Datenübertragung
        transfer_action = QAction('Daten übertragen...', mw)
        transfer_action.triggered.connect(lambda: widget.show_backup_dialog())
        menu.addAction(transfer_action)
        
        # Statistiken aktualisieren
        refresh_action = QAction('Statistiken aktualisieren', mw)
        refresh_action.triggered.connect(lambda: widget.force_refresh())
        menu.addAction(refresh_action)
        
        # Trennlinie
        menu.addSeparator()
        
        # Level-Test
        test_action = QAction('Level-Historie testen', mw)
        test_action.triggered.connect(lambda: test_level_history_direct(widget.db))
        menu.addAction(test_action)
        
        # Trennlinie
        menu.addSeparator()
        
        # Über / Hilfe
        about_action = QAction('Über Study Tracker...', mw)
        about_action.triggered.connect(show_about_dialog)
        menu.addAction(about_action)
        
        # Validierungscode-Test
        test_code_action = QAction('Validierungscodes testen', mw)
        test_code_action.triggered.connect(test_validation_code_recognition)
        menu.addAction(test_code_action)

        # Trennlinie# Trennlinie
        menu.addSeparator()

        # Maintenance section
        maintenance_submenu = QMenu('Maintenance', menu)

        # Validation code cleanup
        cleanup_action = QAction('Clean up duplicate validation codes', mw)
        cleanup_action.triggered.connect(manual_cleanup_validation_codes)
        maintenance_submenu.addAction(cleanup_action)

        # Reimport all validation codes (full refresh)
        reimport_action = QAction('Reimport all validation codes', mw)
        reimport_action.triggered.connect(lambda: reimport_all_validation_codes(widget))
        maintenance_submenu.addAction(reimport_action)

        # Add the submenu
        menu.addMenu(maintenance_submenu)

        print("Study Tracker: Widget erfolgreich erstellt")
        return True
        
    except Exception as e:
        print(f"Study Tracker: Fehler beim Erstellen des Widgets: {e}")
        traceback.print_exc()
        return False

# Direkte Testfunktion für Level-Historie
def test_level_history_direct(db):
    """Führt einen direkten Test der Level-Historie durch"""
    try:
        # GEÄNDERT: Verwende eine negative Deck-ID für Tests, um nicht mit echten Decks zu kollidieren
        test_deck_id = -999
        change_type = "manual_test"
        old_level = 1
        new_level = 2
        
        # In Dialog anzeigen
        msg = QMessageBox()
        msg.setWindowTitle("Level-Historie Test")
        msg.setText("Test der Level-Historie wird ausgeführt...")
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        
        # Direkte Abfrage bestehender Einträge
        cursor = db.conn.execute("SELECT COUNT(*) FROM level_history")
        count = cursor.fetchone()[0]
        
        # Direktes Einfügen
        result = db.save_level_change(test_deck_id, change_type, old_level, new_level)
        
        # Prüfen ob erfolgreich
        cursor = db.conn.execute("""
            SELECT * FROM level_history 
            WHERE change_type = ? AND deck_id = ?
        """, (change_type, test_deck_id))
        entry = cursor.fetchone()
        
        test_result = f"Bestehende Einträge: {count}\n\n"
        test_result += f"Test-Einfügung mit Test-Deck-ID {test_deck_id} erfolgreich: {result}\n\n"
        
        if entry:
            test_result += f"Eintrag gefunden:\nID: {entry[0]}\nDeck: {entry[1]}\nTyp: {entry[2]}\nAlt: {entry[3]}\nNeu: {entry[4]}\nDatum: {entry[5]}"
        else:
            test_result += "FEHLER: Kein Eintrag gefunden!"
        
        msg.setText(test_result)
        msg.exec()
    except Exception as e:
        QMessageBox.critical(None, "Fehler", f"Test-Fehler: {str(e)}")
        traceback.print_exc()


def show_about_dialog():
    """Zeigt einen Dialog mit Informationen über das Add-on"""
    QMessageBox.about(
        mw,
        "Über Study Tracker",
        f"""<h2>Study Tracker {VERSION}</h2>
        <p>Ein Add-on zur Visualisierung und Nachverfolgung von Lernaktivitäten in Anki.</p>
        <p><b>Features:</b></p>
        <ul>
            <li>Heatmap-Visualisierung der Lernaktivität</li>
            <li>Levelsystem für Lernmotivation</li>
            <li>Detaillierte Berichte und Statistiken</li>
            <li>Validierungscodes zur Kompetenzerfassung</li>
        </ul>
        <p>Bei Fragen oder Problemen besuchen Sie bitte die <a href="https://github.com/{GITHUB_REPO}">GitHub-Seite</a>.</p>
        """
    )
def reimport_all_validation_codes(widget):
    """
    Completely purges and reimports all validation codes.
    This is a more aggressive fix for severe validation code problems.
    """
    try:
        if not mw:
            return
            
        # Show confirmation dialog with strong warning
        ret = QMessageBox.warning(
            mw,
            "Study Tracker",
            "This will COMPLETELY PURGE all validation codes and reimport them from your cards.\n\n"
            "Only use this if you're experiencing serious issues with validation codes.\n\n"
            "Do you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if ret != QMessageBox.StandardButton.Yes:
            return
            
        # Create progress dialog
        progress = QProgressDialog("Reimporting validation codes...", "Cancel", 0, 4, mw)
        progress.setWindowTitle("Study Tracker")
        progress.setWindowModality(get_qt_enum(Qt.WindowModality, "WindowModal"))
        progress.setValue(0)
        progress.show()
        QApplication.processEvents()
        
        # Initialize database
        db = Database()
        
        # Step 1: Create backup
        progress.setValue(1)
        progress.setLabelText("Creating backup...")
        QApplication.processEvents()
        
        try:
            backup_dir = os.path.join(ADDON_PATH, "backups")
            os.makedirs(backup_dir, exist_ok=True)
            backup_path = os.path.join(backup_dir, f"validation_codes_backup_{int(time.time())}.csv")
            
            # Get all validation codes
            cursor = db.conn.execute("""
                SELECT id, card_id, deck_id, date, code, correct_percent, difficulty, 
                       page_number, chat_link, card_title, created_at
                FROM validation_codes
            """)
            
            codes = cursor.fetchall()
            
            # Write to CSV
            with open(backup_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['id', 'card_id', 'deck_id', 'date', 'code', 'correct_percent', 
                                'difficulty', 'page_number', 'chat_link', 'card_title', 'created_at'])
                writer.writerows(codes)
                
            print(f"Study Tracker: Created backup at {backup_path}")
        except Exception as e:
            print(f"Study Tracker: Backup error (continuing anyway): {e}")
        
        # Step 2: Count and delete all validation codes
        progress.setValue(2)
        progress.setLabelText("Purging existing validation codes...")
        QApplication.processEvents()
        
        cursor = db.conn.execute("SELECT COUNT(*) FROM validation_codes")
        before_count = cursor.fetchone()[0]
        
        db.conn.execute("DELETE FROM validation_codes")
        db.conn.commit()
        
        # Step 3: Reimport all validation codes
        progress.setValue(3)
        progress.setLabelText("Reimporting validation codes from cards...")
        QApplication.processEvents()
        
        # Create statistics collector for reimporting
        collector = StudyStatisticsCollector(db)
        result = collector.process_validation_codes()
        
        # Process results
        processed_notes = result.get("processed_notes", 0)
        processed_codes = result.get("processed_codes", 0)
        error = result.get("error")
        
        # Step 4: Finalize
        progress.setValue(4)
        progress.setLabelText("Finalizing...")
        QApplication.processEvents()
        
        # Link ChatGPT links with validation codes
        collector.link_chat_links_with_validation_codes()
        
        # Update last cleanup date
        db.save_setting('last_validation_cleanup', datetime.now().strftime("%Y-%m-%d"))
        
        # Count validation codes after reimport
        cursor = db.conn.execute("SELECT COUNT(*) FROM validation_codes")
        after_count = cursor.fetchone()[0]
        
        # Close database connection
        db.close()
        
        # Close progress dialog
        progress.close()
        
        # Show results
        if error:
            QMessageBox.warning(
                mw,
                "Study Tracker",
                f"Validation code reimport completed with errors:\n\n"
                f"Error: {error}\n\n"
                f"Total validation codes before: {before_count}\n"
                f"Current validation codes: {after_count}\n\n"
                f"A backup of the original validation codes was created in the add-on's backup folder."
            )
        else:
            QMessageBox.information(
                mw,
                "Study Tracker",
                f"Validation code reimport completed successfully:\n\n"
                f"Total validation codes before: {before_count}\n"
                f"Current validation codes: {after_count}\n"
                f"Processed notes: {processed_notes}\n"
                f"Processed codes: {processed_codes}\n\n"
                f"A backup of the original validation codes was created in the add-on's backup folder."
            )
        
        # Refresh widget if it exists
        if widget:
            widget.update_stats_and_heatmap()
            
    except Exception as e:
        print(f"Study Tracker: Error in validation code reimport: {e}")
        traceback.print_exc()
        
        # Close progress dialog if it exists
        if 'progress' in locals():
            progress.close()
            
        # Show error
        QMessageBox.critical(
            mw,
            "Study Tracker Error",
            f"Error during validation code reimport:\n\n{str(e)}\n\nCheck the Anki console for details."
        )
        
def manual_cleanup_validation_codes():
    """
    Function for users to manually trigger validation code cleanup.
    Shows a confirmation dialog with results.
    """
    try:
        if not mw:
            return
            
        # Show confirmation dialog
        ret = QMessageBox.question(
            mw,
            "Study Tracker",
            "This will clean up duplicate validation codes in the database.\nDo you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if ret != QMessageBox.StandardButton.Yes:
            return
            
        # Create progress dialog
        progress = QProgressDialog("Cleaning up validation codes...", "Cancel", 0, 3, mw)
        progress.setWindowTitle("Study Tracker")
        progress.setWindowModality(get_qt_enum(Qt.WindowModality, "WindowModal"))
        progress.setValue(0)
        progress.show()
        QApplication.processEvents()
        
        # Initialize database
        db = Database()
        
        # Step 1: Count before cleanup
        progress.setValue(1)
        progress.setLabelText("Counting validation codes...")
        QApplication.processEvents()
        
        cursor = db.conn.execute("SELECT COUNT(*) FROM validation_codes")
        before_count = cursor.fetchone()[0]
        
        # Step 2: Perform cleanup
        progress.setValue(2)
        progress.setLabelText("Removing duplicates...")
        QApplication.processEvents()
        
        deleted_count = cleanup_duplicate_validation_codes(db)
        
        # Step 3: Finalize
        progress.setValue(3)
        progress.setLabelText("Finalizing...")
        QApplication.processEvents()
        
        # Update last cleanup date
        db.save_setting('last_validation_cleanup', datetime.now().strftime("%Y-%m-%d"))
        
        # Close database connection
        db.close()
        
        # Close progress dialog
        progress.close()
        
        # Show results
        QMessageBox.information(
            mw,
            "Study Tracker",
            f"Validation code cleanup completed:\n\n"
            f"Total validation codes before: {before_count}\n"
            f"Duplicate codes removed: {deleted_count}\n"
            f"Current validation codes: {before_count - deleted_count}\n\n"
            f"A backup of the database before cleanup was created in the add-on's backup folder."
        )
        
        # Refresh widget if it exists
        if hasattr(mw, 'study_tracker_widget'):
            QTimer.singleShot(500, lambda: update_widget_safely())
            
    except Exception as e:
        print(f"Study Tracker: Error in manual validation code cleanup: {e}")
        traceback.print_exc()
        
        # Close progress dialog if it exists
        if 'progress' in locals():
            progress.close()
            
        # Show error
        QMessageBox.critical(
            mw,
            "Study Tracker Error",
            f"Error during validation code cleanup:\n\n{str(e)}\n\nCheck the Anki console for details."
        )

def on_review():
    """Hook für die Aktualisierung nach einer Kartenwiederholung"""
    print("Study Tracker: Review erkannt!")
    if hasattr(mw, 'study_tracker_widget'):
        try:
            # Sammle aktuelle Statistiken
            collector = StudyStatisticsCollector(mw.study_tracker_widget.db)
            collector.collect_daily_stats()
            
            # Verwende QTimer.singleShot für verzögerte Aktualisierung
            QTimer.singleShot(100, lambda: update_widget_safely())
        except Exception as e:
            print(f"Study Tracker: Fehler in on_review: {e}")
            traceback.print_exc()
    else:
        print("Study Tracker: Widget nicht gefunden!")


def update_widget_safely():
    """Sichere Aktualisierung des Widgets"""
    try:
        if hasattr(mw, 'study_tracker_widget'):
            print("Study Tracker: Aktualisiere Widget...")
            widget = mw.study_tracker_widget
            
            # Prüfe, ob die Datenbank verfügbar ist
            if not hasattr(widget, 'db') or not widget.db:
                print("Study Tracker: Datenbank nicht verfügbar")
                return
                
            # Prüfe, ob das Level-System verfügbar ist
            if not hasattr(widget, 'level_system') or not widget.level_system:
                print("Study Tracker: Level-System nicht verfügbar")
                return
            
            try:
                # Aktualisiere Level und Fortschritt
                level_result = widget.level_system.check_period_completion()
                if isinstance(level_result, str) and level_result == "level_up":
                    widget.show_level_up_animation()
                
                widget.level_label.setText(f"Level {widget.level_system.current_level}")
                progress = widget.level_system.calculate_progress_percent()
                widget.week_progress_bar.setValue(int(progress))
            except Exception as e:
                print(f"Study Tracker: Fehler bei der Level-Aktualisierung: {e}")
            
            try:
                # Aktualisiere Heatmap
                widget.create_heatmap()
            except Exception as e:
                print(f"Study Tracker: Fehler bei der Heatmap-Aktualisierung: {e}")
            
            try:
                # Aktualisiere Statistiken wenn vorhanden
                if widget.show_stats and hasattr(widget, 'stats_labels'):
                    stats = widget.calculate_stats()
                    widget.update_stats(stats)
            except Exception as e:
                print(f"Study Tracker: Fehler bei der Statistik-Aktualisierung: {e}")
            
            # Erzwinge UI-Update
            QApplication.processEvents()
            
            print("Study Tracker: Widget-Aktualisierung abgeschlossen")
    except Exception as e:
        print(f"Study Tracker: Fehler bei Widget-Aktualisierung: {e}")
        traceback.print_exc()


# Registriere den Review-Hook
addHook("reviewDidEase", on_review)
def test_validation_code_recognition():
    """
    Testet die Erkennung von Validierungscodes in Karten und zeigt Ergebnisse an
    """
    if not mw or not mw.col:
        QMessageBox.warning(
            mw,
            "Study Tracker Test",
            "Anki-Sammlung nicht verfügbar. Test kann nicht durchgeführt werden."
        )
        return
    
    try:
        # Initialisiere temporäre Datenbank
        db = Database()
        
        # Varianten von Validierungscodes, die wir testen
        test_formats = [
            "2025-03-06: 9080",
            "2025-03-06:9080",
            "2025-03-06 9080",
            "2025.03.06: 9080",
            "2025.03.06:9080",
            "2025.03.06 9080"
        ]
        
        validation_pattern = r'(\d{4}[-\.]?\d{2}[-\.]?\d{2})(?:[:]\s*|\s+|:|-)(\d{4})'
        
        # Teste die Regex-Muster
        pattern_results = []
        for test_format in test_formats:
            matches = re.findall(validation_pattern, test_format)
            recognized = len(matches) > 0
            if recognized:
                date_str, code = matches[0]
                pattern_results.append(f"✓ '{test_format}' -> Datum: '{date_str}', Code: '{code}'")
            else:
                pattern_results.append(f"✗ '{test_format}' -> Nicht erkannt")
        
        # Suche nach Notizen mit Validierungscodes
        note_ids = mw.col.find_notes("ValidierungscodesListe:*")
        
        # Sammle die ersten 5 Beispiele
        note_examples = []
        
        for note_id in note_ids[:5]:
            try:
                note = mw.col.get_note(note_id)
                
                if 'ValidierungscodesListe' in note and note['ValidierungscodesListe'].strip():
                    validation_content = note['ValidierungscodesListe'].strip()
                    
                    # Extrahiere Codes mit unserer verbesserten Regex
                    matches = re.findall(validation_pattern, validation_content)
                    
                    example = {
                        'note_id': note_id,
                        'content': validation_content[:100] + ('...' if len(validation_content) > 100 else ''),
                        'matches': matches
                    }
                    
                    note_examples.append(example)
            except Exception as e:
                continue
        
        # Ergebnis anzeigen
        message = "Validierungscode-Erkennungstest:\n\n"
        
        message += "Regex-Muster Test:\n"
        message += "\n".join(pattern_results)
        
        message += "\n\nGefundene Notizen mit ValidierungscodesListe: " + str(len(note_ids))
        
        if note_examples:
            message += "\n\nBeispiele aus Ihren Karten:\n"
            
            for i, example in enumerate(note_examples):
                message += f"\nBeispiel {i+1} (Notiz {example['note_id']}):\n"
                message += f"Inhalt: {example['content']}\n"
                
                if example['matches']:
                    message += f"Erkannte Codes: {len(example['matches'])}\n"
                    for date_str, code in example['matches'][:3]:  # Zeige maximal 3 Codes
                        message += f"  - Datum: {date_str}, Code: {code}\n"
                else:
                    message += "Keine Codes erkannt! Überprüfen Sie das Format.\n"
        
        # Zeige Ergebnisse an
        QMessageBox.information(
            mw,
            "Study Tracker Validierungscode-Test",
            message
        )
        
        # Schließe Datenbankverbindung
        db.close()
    except Exception as e:
        print(f"Study Tracker: Fehler beim Testen der Validierungscode-Erkennung: {e}")
        traceback.print_exc()
        QMessageBox.critical(
            mw,
            "Study Tracker Test Fehler",
            f"Beim Testen der Validierungscode-Erkennung ist ein Fehler aufgetreten:\n\n{str(e)}"
        )
def cleanup_duplicate_validation_codes(db):
    """
    Cleans up duplicate validation codes in the database.
    This function can be called periodically to ensure database integrity.
    
    Args:
        db: Database instance
        
    Returns:
        int: Number of deleted duplicate entries
    """
    try:
        print("Study Tracker: Cleaning up duplicate validation codes...")
        
        # First, create a backup of validation codes
        try:
            backup_dir = os.path.join(ADDON_PATH, "backups")
            os.makedirs(backup_dir, exist_ok=True)
            backup_path = os.path.join(backup_dir, f"validation_codes_backup_{int(time.time())}.csv")
            
            # Get all validation codes
            cursor = db.conn.execute("""
                SELECT id, card_id, deck_id, date, code, correct_percent, difficulty, 
                       page_number, chat_link, card_title, created_at
                FROM validation_codes
            """)
            
            codes = cursor.fetchall()
            
            # Write to CSV
            with open(backup_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['id', 'card_id', 'deck_id', 'date', 'code', 'correct_percent', 
                                'difficulty', 'page_number', 'chat_link', 'card_title', 'created_at'])
                writer.writerows(codes)
                
            print(f"Study Tracker: Created backup at {backup_path}")
        except Exception as e:
            print(f"Study Tracker: Backup error (continuing anyway): {e}")
        
        # Count total validation codes before cleanup
        cursor = db.conn.execute("SELECT COUNT(*) FROM validation_codes")
        before_count = cursor.fetchone()[0]
        
        # Delete duplicate entries, keeping only the most recent entry for each unique card_id + date + code combination
        db.conn.execute("""
            DELETE FROM validation_codes
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM validation_codes
                GROUP BY card_id, date, code
            )
        """)
        
        # Count validation codes after cleanup
        db.conn.commit()
        cursor = db.conn.execute("SELECT COUNT(*) FROM validation_codes")
        after_count = cursor.fetchone()[0]
        
        deleted_count = before_count - after_count
        print(f"Study Tracker: Removed {deleted_count} duplicate validation codes")
        
        return deleted_count
    except Exception as e:
        print(f"Study Tracker: Error cleaning up validation codes: {e}")
        traceback.print_exc()
        return 0


def schedule_periodic_cleanup(interval_days=14):
    """
    Schedules periodic cleanup of validation codes.
    This can be called during add-on initialization.
    
    Args:
        interval_days: Number of days between cleanups
    """
    try:
        print(f"Study Tracker: Scheduling validation code cleanup every {interval_days} days")
        
        # Check when the last cleanup was performed
        db = Database()
        last_cleanup = db.get_setting('last_validation_cleanup')
        
        # If never performed or last performed more than interval_days ago, perform cleanup
        if not last_cleanup:
            # First time, just set the date without cleaning
            db.save_setting('last_validation_cleanup', datetime.now().strftime("%Y-%m-%d"))
            print("Study Tracker: First run, setting initial cleanup date")
        else:
            try:
                last_cleanup_date = datetime.strptime(last_cleanup, "%Y-%m-%d").date()
                today = datetime.now().date()
                days_since_cleanup = (today - last_cleanup_date).days
                
                if days_since_cleanup >= interval_days:
                    print(f"Study Tracker: {days_since_cleanup} days since last cleanup, performing now")
                    deleted_count = cleanup_duplicate_validation_codes(db)
                    db.save_setting('last_validation_cleanup', today.strftime("%Y-%m-%d"))
                    
                    # Log the result
                    if deleted_count > 0:
                        print(f"Study Tracker: Periodic cleanup removed {deleted_count} duplicate validation codes")
                    
                    # Show notification only if significant number of duplicates were removed
                    if deleted_count > 10 and mw:
                        msg = f"Study Tracker removed {deleted_count} duplicate validation codes during scheduled maintenance."
                        tooltip(msg, period=5000)
                else:
                    print(f"Study Tracker: {days_since_cleanup} days since last cleanup, next cleanup in {interval_days - days_since_cleanup} days")
            except Exception as e:
                print(f"Study Tracker: Error processing cleanup date: {e}")
                # Reset the date
                db.save_setting('last_validation_cleanup', datetime.now().strftime("%Y-%m-%d"))
        
        db.close()
    except Exception as e:
        print(f"Study Tracker: Error scheduling validation code cleanup: {e}")
        traceback.print_exc()

def test_report_generation():
    """Testet die Berichtsgenerierung mit Testdaten"""
    try:
        # Initialisiere Datenbank
        db = Database()
        
        # 1. Testdaten einfügen
        print("Study Tracker Test: Erstelle Testdaten...")
        
        # a) Level-Verlauf hinzufügen 
        deck_id = 1  # Standard-ID für Tests
        db.save_level_change(deck_id, "up", 1, 2)  # Level-Up: 1 -> 2
        db.save_level_change(deck_id, "up", 2, 3)  # Level-Up: 2 -> 3
        db.save_level_change(deck_id, "down", 3, 2)  # Level-Down: 3 -> 2
        db.save_level_change(deck_id, "up", 2, 3)  # Level-Up: 2 -> 3
        
        # b) ChatGPT-Link hinzufügen
        card_id = "123456789"  # Dummy-Karten-ID für Tests
        db.save_chat_link(card_id, "https://chat.openai.com/test-link", deck_id, "Testkarte")
        
        # c) Validierungscodes hinzufügen
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        
        # Bessere Korrektheit über Zeit (75 -> 85 -> 95)
        db.save_validation_code(card_id, deck_id, "7503", 0, "https://chat.openai.com/test-link", "Testkarte")
        
        # Setze datum auf yesterday für Test
        cursor = db.conn.execute("""
            UPDATE validation_codes 
            SET date = ? 
            WHERE card_id = ? AND code = ?
        """, (yesterday, card_id, "7503"))
        
        # Zweiter Code mit höherer Korrektheit
        db.save_validation_code(card_id, deck_id, "8504", 0, "https://chat.openai.com/test-link", "Testkarte")
        
        # Dritter Code mit noch höherer Korrektheit
        db.save_validation_code(card_id, deck_id, "9505", 0, "https://chat.openai.com/test-link", "Testkarte")
        
        # d) Lernstatistiken hinzufügen
        for i in range(7):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            db.save_daily_stats(date_str, deck_id, 10, 8, 30)  # 10 fällig, 8 gelernt, 30 min
            
            # Notiere die gelernte Karte
            db.save_studied_card(date_str, card_id, deck_id, 30000)  # 30 Sekunden Lernzeit
        
        # 2. Bericht generieren
        print("Study Tracker Test: Generiere Testbericht...")
        
        report_generator = ReportGenerator(db)
        
        # Zeitraum: letzte 7 Tage
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
        
        html_content = report_generator.generate_report(deck_id, start_date, end_date)
        
        # 3. Bericht speichern für visuelle Inspektion
        test_report_path = os.path.join(ADDON_PATH, "test_report.html")
        with open(test_report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # 4. Ergebnisse prüfen
        validation_count = len(db.get_validation_codes(deck_id, start_date, end_date))
        level_history = db.get_level_history(deck_id, start_date, end_date)
        chat_link = db.get_card_chat_link(card_id)
        
        # Ergebnis-Log
        print("\n----- TEST ERGEBNISSE -----")
        print(f"Bericht erstellt und gespeichert unter: {test_report_path}")
        print(f"Validierungscodes im Bericht: {validation_count}")
        print(f"Level-Änderungen im Bericht: {len(level_history)}")
        print(f"ChatGPT-Link gefunden: {'Ja' if chat_link else 'Nein'}")
        
        # Prüfe auf wichtige HTML-Elemente im Bericht
        success = True
        if "level-chart-container" not in html_content:
            print("❌ Level-Chart nicht gefunden!")
            success = False
        if "competency-view" not in html_content:
            print("❌ Kompetenz-Ansicht nicht gefunden!")
            success = False
        if "chatgpt-badge" not in html_content:
            print("❌ ChatGPT-Badge nicht gefunden!")
            success = False
        
        if success:
            print("✅ Alle erwarteten Elemente wurden im Bericht gefunden!")
        print("---------------------------")
        
        return test_report_path
        
    except Exception as e:
        print(f"Fehler beim Testen der Berichtgenerierung: {e}")
        traceback.print_exc()
        return None
    finally:
        if 'db' in locals():
            db.close()

# Füge einen Menüpunkt für das Starten des Tests hinzu
def add_test_menu_item():
    try:
        if not hasattr(mw, 'study_tracker_menu'):
            # Falls noch kein Menü existiert, überspringe
            return
            
        menu = mw.study_tracker_menu if hasattr(mw, 'study_tracker_menu') else QMenu('Study Tracker', mw)
        
        # Trennlinie
        menu.addSeparator()
        
        # Test-Aktion
        test_action = QAction('Test-Bericht generieren', mw)
        test_action.triggered.connect(lambda: open_test_report())
        menu.addAction(test_action)
        
    except Exception as e:
        print(f"Fehler beim Hinzufügen des Testmenüs: {e}")

def test_field_updates():
    card = Card(mw.col, id=123)
    card['ValidierungscodesListe'] += '|1234'
    card['ChatGPT-Link'] = 'https://chat.openai.com/abc'
    mw.col.update_card(card)
    db = Database()
    assert db.get_validation_codes(123)[0]['code'] == '1234'
    assert db.get_chat_link(123) == 'https://chat.openai.com/abc'

def on_card_edited(note):
    """
    Improved function that processes a card when it's edited.
    Uses the unified validation code processing to ensure consistent handling.
    
    Args:
        note: The edited note
    """
    try:
        print("Study Tracker: Card was edited")
        if not mw or not mw.col or not hasattr(mw, 'study_tracker_widget'):
            return
            
        # Only process notes with relevant fields
        if 'ValidierungscodesListe' not in note and 'ChatGPT-Link' not in note:
            return
            
        # Create temporary database connection for this hook
        db = Database()
        
        # Create a statistics collector and process this specific note
        collector = StudyStatisticsCollector(db)
        result = collector.process_validation_codes(specific_note=note)
        
        # Log results
        processed_notes = result.get("processed_notes", 0)
        processed_codes = result.get("processed_codes", 0)
        error = result.get("error")
        
        if error:
            print(f"Study Tracker: Error processing edited note: {error}")
        else:
            print(f"Study Tracker: Successfully processed edited note: {processed_codes} codes from {processed_notes} notes")
        
        # Update widget if it exists
        if hasattr(mw, 'study_tracker_widget'):
            QTimer.singleShot(500, lambda: update_widget_safely())
            
        # Close temporary database connection
        db.close()
    except Exception as e:
        print(f"Study Tracker: Error in on_card_edited: {e}")
        traceback.print_exc()

def on_sync_finished():
    """Wird aufgerufen, wenn die Synchronisierung mit AnkiWeb abgeschlossen ist"""
    try:
        print("Study Tracker: Synchronisierung abgeschlossen")
        if not mw or not hasattr(mw, 'study_tracker_widget'):
            return
            
        # Nach erfolgreicher Synchronisierung alle Daten aktualisieren
        # Verwende QTimer.singleShot, um die Aktualisierung zu verzögern,
        # damit die Benutzeroberfläche nicht blockiert wird
        QTimer.singleShot(1000, lambda: update_all_data_after_sync())
    except Exception as e:
        print(f"Study Tracker: Fehler in on_sync_finished: {e}")
        traceback.print_exc()

def update_all_data_after_sync():
    """Aktualisiert alle Daten nach der Synchronisierung"""
    try:
        if not hasattr(mw, 'study_tracker_widget'):
            return
            
        widget = mw.study_tracker_widget
        
        # Sammle neue Statistiken
        collector = StudyStatisticsCollector(widget.db)
        collector.collect_daily_stats()
        collector.import_historical_revlog()
        collector.parse_validation_codes_from_cards()
        collector.link_chat_links_with_validation_codes()
        
        # Aktualisiere Widget
        widget.create_heatmap()
        widget.update_stats_and_heatmap()
        
        print("Study Tracker: Daten nach Synchronisierung aktualisiert")
    except Exception as e:
        print(f"Study Tracker: Fehler bei der Aktualisierung nach Synchronisierung: {e}")
        traceback.print_exc()


# Registriere die Hooks für Anki-Events

# Nach dem Bearbeiten einer Notiz/Karte
try:
    from aqt.gui_hooks import editor_did_save_note
    editor_did_save_note.append(lambda note_editor: on_card_edited(note_editor.note))
except ImportError:
    print("Study Tracker: Konnte editor_did_save_note-Hook nicht registrieren")

# Nach der Synchronisierung mit AnkiWeb
try:
    from aqt.gui_hooks import sync_did_finish
    sync_did_finish.append(on_sync_finished)
except ImportError:
    print("Study Tracker: Konnte sync_did_finish-Hook nicht registrieren")

# Starte die Initialisierung
if mw is not None:
    QTimer.singleShot(2000, initialize_addon)

def test_level_history():
    """Testet, ob Leveländerungen korrekt gespeichert werden"""
    try:
        print("===== Test Level-Historie =====")
        db = Database()
        deck_id = 1  # Test-Deck ID
        
        # Prüfen, ob die Tabelle existiert
        cursor = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='level_history'")
        if not cursor.fetchone():
            print("KRITISCHER FEHLER: Tabelle level_history existiert nicht!")
            return False
            
        # Prüfen, ob die Tabelle die erwartete Struktur hat
        cursor = db.conn.execute("PRAGMA table_info(level_history)")
        columns = cursor.fetchall()
        print(f"Tabellenstruktur: {columns}")
        
        # Prüfen, ob bereits Einträge existieren
        cursor = db.conn.execute("SELECT COUNT(*) FROM level_history")
        count = cursor.fetchone()[0]
        print(f"Bestehende Einträge: {count}")
        
        # Direktes Einfügen zum Test (umgeht die reguläre Methode)
        direct_insert = db.conn.execute("""
            INSERT INTO level_history 
            (deck_id, change_type, old_level, new_level, change_date) 
            VALUES (?, ?, ?, ?, ?)
        """, (
            deck_id, 
            "test_direct", 
            1, 
            2, 
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        db.conn.commit()
        
        # Prüfen, ob der direkte Eintrag vorhanden ist
        cursor = db.conn.execute("""
            SELECT * FROM level_history 
            WHERE change_type = 'test_direct'
        """)
        direct_result = cursor.fetchone()
        if direct_result:
            print(f"Direkter Eintrag gefunden: {direct_result}")
        else:
            print("FEHLER: Direkter Eintrag nicht gefunden!")
        
        # Test mit der regulären Methode
        success = db.save_level_change(deck_id, "test_method", 2, 3)
        print(f"Reguläre Methode erfolgreich: {success}")
        
        # Prüfen, ob der reguläre Eintrag vorhanden ist
        cursor = db.conn.execute("""
            SELECT * FROM level_history 
            WHERE change_type = 'test_method'
        """)
        method_result = cursor.fetchone()
        if method_result:
            print(f"Regulärer Eintrag gefunden: {method_result}")
        else:
            print("FEHLER: Regulärer Eintrag nicht gefunden!")
        
        # Einträge abfragen und anzeigen
        cursor = db.conn.execute("SELECT * FROM level_history ORDER BY change_date DESC LIMIT 5")
        results = cursor.fetchall()
        for result in results:
            print(f"Eintrag: {result}")
        
        db.conn.commit()
        db.close()
        
        print("===== Test abgeschlossen =====")
        return direct_result is not None and method_result is not None
    except Exception as e:
        print(f"Fehler beim Testen der Level-Historie: {e}")
        traceback.print_exc()
        return False

def debug_report_level_history():
    """Debug-Funktion für die Level-Historie im Bericht"""
    try:
        db = Database()
        
        # Direkter Datenbankzugriff
        cursor = db.conn.execute("""
            SELECT change_date, change_type, old_level, new_level
            FROM level_history
            ORDER BY change_date DESC
            LIMIT 10
        """)
        results = cursor.fetchall()
        
        # Erstelle Bericht-Generator
        report_gen = ReportGenerator(db)
        
        # Hole die aktuellen Daten
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Hole Beispiel-Deck
        deck_id = 1  # Standard für Tests
        
        # Hole Level-Historie mit der Methode
        level_history = db.get_level_history(deck_id, yesterday, today)
        
        # Füge Level-Änderung hinzu, falls keine vorhanden
        if not level_history:
            db.save_level_change(deck_id, "debug_test", 1, 2)
            level_history = db.get_level_history(deck_id, yesterday, today)
        
        # Erstelle Test-Dialog
        from aqt.qt import QDialog, QVBoxLayout, QLabel, QTextEdit, QPushButton
        
        dialog = QDialog(mw)
        dialog.setWindowTitle("Level-Historie Debug")
        dialog.resize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # Info-Label
        info = QLabel(f"Gefunden: {len(results)} Level-Historie-Einträge in der Datenbank")
        layout.addWidget(info)
        
        # Text-Bereich für Daten
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        
        debug_text = "DIREKTE DATENBANKABFRAGE:\n"
        for row in results:
            debug_text += f"Datum: {row[0]}, Typ: {row[1]}, Alt: {row[2]}, Neu: {row[3]}\n"
        
        debug_text += "\n\nGET_LEVEL_HISTORY METHODE:\n"
        for item in level_history:
            debug_text += (f"Datum: {item.get('date', 'FEHLER')}, " +
                         f"Typ: {item.get('change_type', 'FEHLER')}, " +
                         f"Alt: {item.get('old_level', 'FEHLER')}, " +
                         f"Neu: {item.get('new_level', 'FEHLER')}\n")
        
        # JSON-Test
        import json
        history_json = json.dumps(level_history)
        debug_text += f"\n\nJSON STRING (gekürzt):\n{history_json[:200]}...\n"
        
        # Zurückparsen
        try:
            parsed = json.loads(history_json)
            debug_text += f"\nPARSED BACK FROM JSON (erstes Element):\n{parsed[0] if parsed else 'Leer'}"
        except Exception as e:
            debug_text += f"\nJSON PARSE ERROR: {e}"
        
        text_edit.setText(debug_text)
        layout.addWidget(text_edit)
        
        # Schließen-Button
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.exec()
        
        db.close()
    except Exception as e:
        print(f"Debug error: {e}")
        traceback.print_exc()

# Menüeintrag für die Debug-Funktion
if mw is not None:
    debug_action = QAction("Level-Historie Debug", mw)
    debug_action.triggered.connect(debug_report_level_history)
    mw.form.menuTools.addAction(debug_action)

def purge_and_reimport_validation_codes():
    """
    A comprehensive function to fix the validation codes issues:
    1. Purges all existing validation codes from the database
    2. Reimports validation codes directly from Anki cards
    3. Correctly associates codes with their respective cards
    """
    try:
        # Create database connection
        db = Database()
        
        # Step 1: Back up the database before purging
        try:
            backup_dir = os.path.join(ADDON_PATH, "backups")
            os.makedirs(backup_dir, exist_ok=True)
            backup_path = os.path.join(backup_dir, f"validation_codes_backup_{int(time.time())}.csv")
            
            # Get all validation codes
            cursor = db.conn.execute("""
                SELECT id, card_id, deck_id, date, code, correct_percent, difficulty, 
                       page_number, chat_link, card_title, created_at
                FROM validation_codes
            """)
            
            codes = cursor.fetchall()
            
            # Write to CSV
            with open(backup_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['id', 'card_id', 'deck_id', 'date', 'code', 'correct_percent', 
                                'difficulty', 'page_number', 'chat_link', 'card_title', 'created_at'])
                writer.writerows(codes)
                
            print(f"Study Tracker: Created backup at {backup_path}")
        except Exception as e:
            print(f"Study Tracker: Backup error (continuing anyway): {e}")
        
        # Step 2: Purge all existing validation codes
        print("Study Tracker: Purging all existing validation codes...")
        cursor = db.conn.execute("SELECT COUNT(*) FROM validation_codes")
        before_count = cursor.fetchone()[0]
        
        db.conn.execute("DELETE FROM validation_codes")
        db.conn.commit()
        
        print(f"Study Tracker: Purged {before_count} existing validation codes")
        
        # Step 3: Reimport validation codes from cards with enhanced handling
        print("Study Tracker: Reimporting validation codes from cards...")
        
        # Improved regex for validation codes with various formats
        validation_pattern = r'(\d{4}[-\.]\d{2}[-\.]\d{2})(?:[:]\s*|\s+|:|-)(\d{4})'
        
        # Set to track unique codes to prevent duplicates
        processed_codes = set()
        
        # Count imported codes
        imported_count = 0
        
        # Get all notes with ValidationCodesListe field
        if not mw or not mw.col:
            raise Exception("Anki collection not available")
            
        note_ids = mw.col.find_notes("ValidierungscodesListe:*")
        print(f"Study Tracker: Found {len(note_ids)} notes with ValidationCodesListe field")
        
        for note_id in note_ids:
            try:
                note = mw.col.get_note(note_id)
                
                # Skip if no validation codes
                if 'ValidierungscodesListe' not in note or not note['ValidierungscodesListe'].strip():
                    continue
                    
                validation_content = note['ValidierungscodesListe'].strip()
                chat_link = note['ChatGPT-Link'].strip() if 'ChatGPT-Link' in note else ''
                
                # Get all cards for this note
                card_ids = note.card_ids()
                if not card_ids:
                    continue
                
                # Get card and deck info for the first card (all cards in note share content)
                card = mw.col.get_card(card_ids[0])
                deck_id = card.did
                card_id_str = str(card_ids[0])
                
                # Get card title
                title_getter = ValidationCodeHandler(db)
                card_title = title_getter.get_card_title(card_id_str)
                
                # Extract validation codes using regex
                all_codes = re.findall(validation_pattern, validation_content)
                if not all_codes:
                    print(f"Study Tracker: No validation codes found in note {note_id}")
                    continue
                
                print(f"Study Tracker: Found {len(all_codes)} validation codes in note {note_id}")
                
                # Process each validation code
                for date_str, code in all_codes:
                    # Normalize date format
                    date_str = date_str.replace('.', '-')
                    
                    # Create unique key to prevent duplicates
                    unique_key = f"{card_id_str}_{date_str}_{code}"
                    
                    if unique_key in processed_codes:
                        print(f"Study Tracker: Skipping duplicate: {date_str}: {code} for card {card_id_str}")
                        continue
                    
                    # Parse code components
                    correct_percent = int(code[:2]) if len(code) >= 2 else 0
                    difficulty = int(code[2:4]) if len(code) >= 4 else 0
                    
                    # Insert the validation code directly
                    db.conn.execute("""
                        INSERT INTO validation_codes
                        (card_id, deck_id, date, code, correct_percent, difficulty, 
                         page_number, chat_link, card_title, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        card_id_str,
                        deck_id,
                        date_str,
                        code,
                        correct_percent,
                        difficulty,
                        0,  # page_number default
                        chat_link,
                        card_title,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ))
                    
                    # Add to processed set and increment counter
                    processed_codes.add(unique_key)
                    imported_count += 1
                    
                    print(f"Study Tracker: Imported {date_str}: {code} for card {card_id_str}")
                
                # Save ChatGPT link if available
                if chat_link:
                    db.save_chat_link(card_id_str, chat_link, deck_id, card_title)
                    
            except Exception as e:
                print(f"Study Tracker: Error processing note {note_id}: {e}")
                traceback.print_exc()
        
        # Commit all changes
        db.conn.commit()
        
        # Final count verification
        cursor = db.conn.execute("SELECT COUNT(*) FROM validation_codes")
        after_count = cursor.fetchone()[0]
        
        print(f"Study Tracker: Successfully reimported {imported_count} validation codes")
        print(f"Study Tracker: Database now contains {after_count} validation codes")
        
        # Show message to user
        QMessageBox.information(
            mw,
            "Study Tracker",
            f"Validation codes successfully cleaned and reimported:\n\n"
            f"Removed: {before_count} duplicate/invalid codes\n"
            f"Added: {imported_count} valid codes\n\n"
            f"Database now contains {after_count} validation codes.\n"
            f"A backup of the old codes was saved in the add-on's backup folder."
        )
        
        # Close the database connection
        db.close()
        
        return True
    except Exception as e:
        print(f"Study Tracker: Error during validation code cleanup: {e}")
        traceback.print_exc()
        
        # Show error to user
        QMessageBox.critical(
            mw,
            "Study Tracker Error",
            f"Error cleaning validation codes:\n\n{str(e)}\n\nCheck the Anki console for details."
        )
        
        return False

def add_cleanup_menu_item():
    """
    Adds a menu item to clean up and reimport validation codes.
    """
    try:
        # Get menu
        menu = mw.form.menuTools
        
        # Add cleanup action
        cleanup_action = QAction('Study Tracker: Fix Validation Codes', mw)
        cleanup_action.triggered.connect(purge_and_reimport_validation_codes)
        menu.addAction(cleanup_action)
        
        print("Study Tracker: Added validation code cleanup menu item")
    except Exception as e:
        print(f"Study Tracker: Error adding cleanup menu item: {e}")

# Add this line at the end of the file
if mw is not None:
    add_cleanup_menu_item()
