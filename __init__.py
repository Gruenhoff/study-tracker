from aqt import mw
from aqt.qt import *
from anki.hooks import addHook
import sqlite3
from datetime import datetime, timedelta
import os
import csv
import glob
import shutil
from aqt.utils import showInfo  # Füge diese Zeile hinzu
import time  # Wird für time.time() in handle_db_error benötigt
import traceback  # Wird für traceback.print_exc() benötigt
import json  # Am Anfang der Datei bei den anderen Imports
import html
import hashlib
import traceback
import urllib.request
import json

GITHUB_REPO = "Gruenhoff/study-tracker"
VERSION = "1.0.0"

def check_updates():
   try:
       url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
       response = urllib.request.urlopen(url)
       data = json.loads(response.read())
       latest_version = data["tag_name"].strip("v")
       
       if latest_version > VERSION:
           showInfo(f"Neue Version {latest_version} verfügbar!\n"
                   f"Download: github.com/{GITHUB_REPO}/releases")
   except:
       pass

# Qt6 Imports explizit definieren
QDockWidget = QDockWidget
Qt = Qt
QWidget = QWidget
QVBoxLayout = QVBoxLayout
QHBoxLayout = QHBoxLayout
QLabel = QLabel
QPushButton = QPushButton
QProgressBar = QProgressBar
QGridLayout = QGridLayout
QFrame = QFrame
QDialog = QDialog
QListWidget = QListWidget
QDialogButtonBox = QDialogButtonBox
QDateEdit = QDateEdit
QFileDialog = QFileDialog
QMessageBox = QMessageBox
QTimer = QTimer
QPropertyAnimation = QPropertyAnimation
QEasingCurve = QEasingCurve
QPoint = QPoint
QMenu = QMenu
QAction = QAction

# Konstanten
DB_PATH = os.path.join(mw.pm.addonFolder(), "learning_stats.db")
BACKUP_DIR = os.path.join(mw.pm.addonFolder(), "backups")
MOBILE_SCREEN_WIDTH = 600  # Pixel für Smartphone-Erkennung

print("Study Tracker: Starting initialization...")

def initialize_clean_start():
    """Initialisiert einen sauberen Start des Study Trackers"""
    db = Database()
    try:
        # Prüfe, ob es bereits einen Installationszeitpunkt gibt
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT value FROM settings 
            WHERE key = 'installation_date'
        """)
        installation_date = cursor.fetchone()
        
        if not installation_date:
            # Erster Start - setze Installationsdatum
            today = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("""
                INSERT INTO settings (key, value)
                VALUES ('installation_date', ?)
            """, (today,))
            
            # Lösche eventuell vorhandene alte Statistiken
            cursor.execute("DELETE FROM daily_stats")
            cursor.execute("DELETE FROM level_progress")
            cursor.execute("DELETE FROM level_history")
            
            # Initialisiere Level-System mit Level 1
            cursor.execute("""
                INSERT INTO level_progress 
                (current_level, level_start_date, last_updated)
                VALUES (1, ?, ?)
            """, (today, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
            db.conn.commit()
            
            # Zeige Willkommensnachricht
            QMessageBox.information(None, 
                "Study Tracker Installation",
                f"""Willkommen beim Study Tracker!

Der Study Tracker beginnt ab heute ({today}) mit der Aufzeichnung deiner Lernstatistiken.

Dein Fortschritt wird von diesem Zeitpunkt an genau verfolgt."""
            )
            
            print(f"Study Tracker: Clean start initialized on {today}")
            return True
            
        return False
        
    except Exception as e:
        print(f"Error in initialize_clean_start: {e}")
        traceback.print_exc()
        return False
    finally:
        db.close()

def get_tracking_start_date():
    """Holt das Startdatum des Trackings"""
    db = Database()
    try:
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT value FROM settings 
            WHERE key = 'installation_date'
        """)
        result = cursor.fetchone()
        return result[0] if result else datetime.now().strftime("%Y-%m-%d")
    finally:
        db.close()

class Database:
    """Verbesserte Datenbankklasse mit robusterer Fehlerbehandlung"""
    def __init__(self):
        print("Study Tracker: Initializing database connection")
        self.conn = None
        try:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            self.conn = sqlite3.connect(DB_PATH)
            self.create_tables()
            migrate_database(self)  # Führe Migrationen aus
            print("Study Tracker: Database connection established")
        except Exception as e:
            print(f"Study Tracker: Database initialization failed: {e}")
            self.handle_db_error(e)

    def create_tables(self):
        try:
            with self.conn:
                self.conn.executescript("""
                    CREATE TABLE IF NOT EXISTS daily_stats (
                        date TEXT,
                        deck_id INTEGER,
                        cards_due INTEGER DEFAULT 0,
                        cards_studied INTEGER DEFAULT 0,
                        study_time INTEGER DEFAULT 0,
                        PRIMARY KEY (date, deck_id)
                    );
                    
                    CREATE TABLE IF NOT EXISTS level_progress (
                        id INTEGER PRIMARY KEY,
                        current_level INTEGER DEFAULT 1,
                        level_start_date TEXT,
                        last_updated TEXT
                    );
                    
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    );
                    
                    CREATE TABLE IF NOT EXISTS validation_codes (
                        id INTEGER PRIMARY KEY,
                        deck_id INTEGER,
                        date TEXT,
                        code TEXT,
                        page_number INTEGER,
                        chat_link TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS level_history (
                        id INTEGER PRIMARY KEY,
                        deck_id INTEGER,
                        change_type TEXT,
                        old_level INTEGER,
                        new_level INTEGER,
                        change_date TEXT
                    );
                    
                    CREATE INDEX IF NOT EXISTS idx_daily_stats_date 
                    ON daily_stats(date);
                    
                    CREATE INDEX IF NOT EXISTS idx_daily_stats_deck 
                    ON daily_stats(deck_id);
                    
                    CREATE INDEX IF NOT EXISTS idx_level_history_deck 
                    ON level_history(deck_id);
                """)
                print("Study Tracker: Database tables created successfully")
        except Exception as e:
            print(f"Study Tracker: Failed to create tables: {e}")
            self.handle_db_error(e)
        try:
            with self.conn:
                self.conn.executescript("""
                    -- Bestehende Tabellen...
                    
                    CREATE TABLE IF NOT EXISTS streak_records (
                        id INTEGER PRIMARY KEY,
                        record INTEGER NOT NULL,
                        date TEXT NOT NULL
                    );
                """)
                print("Study Tracker: Database tables created successfully")
        except Exception as e:
            print(f"Study Tracker: Failed to create tables: {e}")
            self.handle_db_error(e)

    def handle_db_error(self, error):
        """Zentrale Fehlerbehandlung für Datenbankoperationen"""
        print(f"Database error: {str(error)}")
        print("Stack trace:")
        traceback.print_exc()
        
        try:
            # Versuche Backup zu erstellen bei Datenbankfehlern
            if self.conn:
                backup_path = os.path.join(
                    BACKUP_DIR, 
                    f"study_tracker_backup_{int(time.time())}.db"
                )
                os.makedirs(BACKUP_DIR, exist_ok=True)
                with sqlite3.connect(backup_path) as backup_db:
                    self.conn.backup(backup_db)
                print(f"Database backup created at: {backup_path}")
        except Exception as backup_error:
            print(f"Failed to create backup: {backup_error}")

    def save_selected_deck(self, deck_name):
        """Speichert den ausgewählten Stapel"""
        try:
            with self.conn:  # Automatisches Transaction Management
                self.conn.execute("""
                    INSERT OR REPLACE INTO settings (key, value)
                    VALUES ('selected_deck', ?)
                """, (deck_name,))
            print(f"Study Tracker: Saved selected deck: {deck_name}")
        except Exception as e:
            print(f"Study Tracker: Failed to save selected deck: {e}")
            self.handle_db_error(e)

    def get_selected_deck(self):
        """Lädt den gespeicherten Stapel"""
        try:
            cursor = self.conn.execute("""
                SELECT value FROM settings WHERE key = 'selected_deck'
            """)
            result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            print(f"Study Tracker: Failed to get selected deck: {e}")
            self.handle_db_error(e)
            return None

    def close(self):
        """Schließt die Datenbankverbindung"""
        if hasattr(self, 'conn') and self.conn:
            try:
                self.conn.commit()  # Stelle sicher, dass alle Änderungen gespeichert sind
                self.conn.close()
                print("Study Tracker: Database connection closed successfully")
            except Exception as e:
                print(f"Study Tracker: Error closing database: {e}")
                self.handle_db_error(e)

    def export_backup(self, backup_path, password=None):
        """Erstellt ein Backup der Datenbank"""
        try:
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            with sqlite3.connect(backup_path) as backup_db:
                self.conn.backup(backup_db)
                
            if password:
                if not self.encrypt_file(backup_path, password):
                    return False
            return True
        except Exception as e:
            print(f"Backup failed: {e}")
            self.handle_db_error(e)
            return False

    def import_backup(self, backup_path, password=None):
        """Importiert ein Backup"""
        try:
            if password:
                # Erstelle temporäre Kopie für Entschlüsselung
                temp_path = backup_path + '.temp'
                shutil.copy2(backup_path, temp_path)
                
                if not self.decrypt_file(temp_path, password):
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
            print(f"Import failed: {e}")
            self.handle_db_error(e)
            return False

    def encrypt_file(self, file_path, password):
        """Verschlüsselt eine Datei mit einem Passwort"""
        try:
            # Erstelle einen Hash des Passworts
            key = hashlib.sha256(password.encode()).digest()
            
            # Lese die Original-Datei
            with open(file_path, 'rb') as f:
                data = f.read()
            
            # Verschlüssele die Daten
            encrypted_data = bytearray()
            for i in range(len(data)):
                encrypted_data.append(data[i] ^ key[i % len(key)])
            
            # Speichere die verschlüsselten Daten
            with open(file_path, 'wb') as f:
                f.write(encrypted_data)
            return True
        except Exception as e:
            print(f"Encryption failed: {e}")
            return False
    def save_validation_code(self, deck_id, code, page_number, chat_link):
        """Speichert einen Validierungscode in der Datenbank"""
        try:
            with self.conn:
                self.conn.execute("""
                    INSERT INTO validation_codes
                    (deck_id, date, code, page_number, chat_link)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    deck_id,
                    datetime.now().strftime("%Y-%m-%d"),
                    code,
                    page_number,
                    chat_link
                ))
                return True
        except Exception as e:
            print(f"Error saving validation code: {e}")
            self.handle_db_error(e)
            return False

    def decrypt_file(self, file_path, password):
        """Entschlüsselt eine Datei mit einem Passwort"""
        try:
            # Erstelle einen Hash des Passworts
            key = hashlib.sha256(password.encode()).digest()
            
            # Lese die verschlüsselte Datei
            with open(file_path, 'rb') as f:
                encrypted_data = f.read()
            
            # Entschlüssele die Daten
            decrypted_data = bytearray()
            for i in range(len(encrypted_data)):
                decrypted_data.append(encrypted_data[i] ^ key[i % len(key)])
                
            # Speichere die entschlüsselten Daten
            with open(file_path, 'wb') as f:
                f.write(decrypted_data)
            return True
        except Exception as e:
            print(f"Decryption failed: {e}")
            return False

def migrate_database(db):
    try:
        with db.conn:
            # Prüfe auf alte Tabellenstruktur
            cursor = db.conn.cursor()
            cursor.execute("PRAGMA table_info(level_progress)")
            columns = cursor.fetchall()
            
            # Füge fehlende Spalten hinzu
            if any(col[1] == 'weeks_completed' for col in columns):
                db.conn.executescript("""
                    -- Backup alte Daten
                    CREATE TEMPORARY TABLE level_backup AS 
                    SELECT * FROM level_progress;
                    
                    -- Erstelle neue Struktur
                    DROP TABLE level_progress;
                    CREATE TABLE level_progress (
                        id INTEGER PRIMARY KEY,
                        current_level INTEGER DEFAULT 1,
                        level_start_date TEXT,
                        last_updated TEXT
                    );
                    
                    -- Übertrage Daten
                    INSERT INTO level_progress (current_level, last_updated)
                    SELECT current_level, last_updated 
                    FROM level_backup;
                    
                    DROP TABLE level_backup;
                """)
            
            # Erstelle neue Tabellen
            db.conn.executescript("""
                CREATE TABLE IF NOT EXISTS level_history (
                    id INTEGER PRIMARY KEY,
                    deck_id INTEGER,
                    change_type TEXT,
                    old_level INTEGER,
                    new_level INTEGER,
                    change_date TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_level_history_deck 
                ON level_history(deck_id);
            """)
    except Exception as e:
        print(f"Migration error: {e}")
        db.handle_db_error(e)


def save_daily_stats():
    """Verbesserte Funktion zum Speichern der täglichen Statistiken"""
    print("\nStudy Tracker: Starting save_daily_stats...")
    
    db = Database()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Millisekunden-Timestamp für heute 00:00
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_ms = int(today_start.timestamp() * 1000)
    
    # Millisekunden-Timestamp für heute 23:59
    today_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
    today_end_ms = int(today_end.timestamp() * 1000)
    
    try:
        decks = mw.col.decks.all()
        print(f"Processing {len(decks)} decks...")
        
        for deck in decks:
            deck_id = int(deck['id'])
            deck_name = deck['name']
            print(f"\nProcessing deck: {deck_name} (ID: {deck_id})")
            
            try:
                # Fällige Karten für den heutigen Tag
                due_cards_query = f'deck:"{deck_name}" (is:new or is:due)'
                due_cards = len(mw.col.find_cards(due_cards_query))
                
                # Gelernte Karten für den heutigen Tag
                cards_studied = mw.col.db.scalar(f"""
                    SELECT COUNT(DISTINCT cid) 
                    FROM revlog r 
                    JOIN cards c ON r.cid = c.id 
                    WHERE c.did = {deck_id} 
                    AND r.id BETWEEN {today_start_ms} AND {today_end_ms}
                """) or 0
                
                # Lernzeit berechnen (in Minuten)
                study_time = mw.col.db.scalar(f"""
                    SELECT CAST(COALESCE(SUM(time) / 60.0, 0) AS INTEGER)
                    FROM revlog r
                    JOIN cards c ON r.cid = c.id
                    WHERE c.did = {deck_id}
                    AND r.id BETWEEN {today_start_ms} AND {today_end_ms}
                """) or 0
                
                print(f"Stats for {deck_name}: Due={due_cards}, Studied={cards_studied}, Time={study_time}")
                
                # Speichere die Statistiken
                with db.conn:
                    db.conn.execute("""
                        INSERT OR REPLACE INTO daily_stats 
                        (date, deck_id, cards_due, cards_studied, study_time)
                        VALUES (?, ?, ?, ?, ?)
                    """, (today, deck_id, due_cards, cards_studied, study_time))
                    
            except Exception as deck_error:
                print(f"Error processing deck {deck_name}: {deck_error}")
                continue
        
        print("Study Tracker: All daily stats saved successfully")
        
    except Exception as e:
        print(f"Error in save_daily_stats: {e}")
        traceback.print_exc()
    finally:
        db.close()

    def save_validation_code(deck_id, code, page_number, chat_link):
        """Speichert einen Validierungscode"""
        db = Database()
        today = datetime.now().strftime("%Y-%m-%d")
        
        try:
            with db.conn:
                db.conn.execute("""
                    INSERT OR REPLACE INTO validation_codes
                    (deck_id, date, code, page_number, chat_link)
                    VALUES (?, ?, ?, ?, ?)
                """, (deck_id, today, code, page_number, chat_link))
                return True
        except Exception as e:
            print(f"Error saving validation code: {e}")
            return False
        finally:
            db.close()

class LevelSystem:
    def __init__(self, db, deck_id=None):
        self.db = db
        self.deck_id = deck_id
        self.current_level = 1
        self.period_start_date = None
        self.load_progress()

    def load_progress(self):
        """Loads the current level state and period start"""
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT current_level, level_start_date, id
                FROM level_progress
                ORDER BY last_updated DESC
                LIMIT 1
            """)
            row = cursor.fetchone()
            
            if row:
                self.current_level = row[0] if row[0] is not None else 1
                # Handle potentially null level_start_date
                if row[1] is not None:
                    try:
                        self.period_start_date = datetime.strptime(row[1], "%Y-%m-%d").date()
                    except ValueError:
                        print(f"Invalid date format in database: {row[1]}")
                        self.period_start_date = datetime.now().date()
                else:
                    self.period_start_date = datetime.now().date()
            else:
                # No existing progress, initialize with defaults
                self.initialize_new_progress()
        except Exception as e:
            print(f"Error loading level progress: {e}")
            self.initialize_new_progress()

    def initialize_new_progress(self):
        """Initializes new progress record with default values"""
        self.current_level = 1
        self.period_start_date = datetime.now().date()
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("""
                INSERT INTO level_progress 
                (current_level, level_start_date, last_updated)
                VALUES (?, ?, ?)
            """, (
                self.current_level,
                self.period_start_date.strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            self.db.conn.commit()
        except Exception as e:
            print(f"Error initializing new progress: {e}")

    def save_progress(self):
        """Saves the current progress to the database"""
        try:
            with self.db.conn:  # Use context manager for automatic commit/rollback
                self.db.conn.execute("""
                    INSERT OR REPLACE INTO level_progress 
                    (current_level, level_start_date, last_updated)
                    VALUES (?, ?, ?)
                """, (
                    self.current_level,
                    self.period_start_date.strftime("%Y-%m-%d"),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
        except Exception as e:
            print(f"Error saving progress: {e}")

    def check_period_completion(self):
        """Prüft ob die aktuelle Periode abgeschlossen ist"""
        today = datetime.now().date()
        days_passed = (today - self.period_start_date).days
        
        if days_passed >= 7:
            successful_days = self.count_successful_days()
            
            if successful_days >= 5:
                self.level_up()
            else:
                self.level_down()
                
            # Starte neue Periode
            self.period_start_date = today
            self.save_progress()
            return True
        return False

    def count_successful_days(self):
        """Zählt erfolgreiche Lerntage in der aktuellen Periode"""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT COUNT(DISTINCT date)
            FROM daily_stats
            WHERE date BETWEEN ? AND ?
            AND cards_studied >= cards_due
            AND deck_id = ?
        """, (
            self.period_start_date.strftime("%Y-%m-%d"),
            (self.period_start_date + timedelta(days=6)).strftime("%Y-%m-%d"),
            self.deck_id
        ))
        return cursor.fetchone()[0] or 0

    def check_level_progress(self):
        """Prüft den Level-Fortschritt und stuft ggf. zurück"""
        if not self.period_start_date:
            return
        
        today = datetime.now().date()
        days_passed = (today - self.period_start_date).days
        remaining_days = 7 - days_passed
        successful_days = self.count_successful_days()
        needed_days = 5 - successful_days
        
        # Wenn das Ziel nicht mehr erreichbar ist
        if needed_days > remaining_days:
            if self.current_level > 1:
                self.level_down()
            else:
                # Bei Level 1: Nur Fortschritt zurücksetzen
                self.period_start_date = today
            self.save_progress()

    def level_down(self):
        """Führt ein Level-Down durch und speichert den Verlauf"""
        if self.current_level > 1:
            self.current_level -= 1
            self.save_level_change("down")
            self.show_level_down_notification()

    def save_level_change(self, change_type):
        """Speichert Level-Änderungen für die Historie"""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            INSERT INTO level_history (
                deck_id, 
                change_type,
                old_level,
                new_level,
                change_date
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            self.deck_id,
            change_type,
            self.current_level - (1 if change_type == "up" else -1),
            self.current_level,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        self.db.conn.commit()

    def calculate_weekly_progress(self):
        if not self.period_start_date:
            return 0
        successful_days = self.count_successful_days()
        progress = min((successful_days / 5.0) * 100, 100)
        self.check_period_completion()  # Prüfe auf Level-Up/Down
        return progress

    def show_level_up_notification(self):
        """Zeigt Level-Up Benachrichtigung"""
        QMessageBox.information(None, 
            "Level Up!",
            f"Glückwunsch! Du hast Level {self.current_level} erreicht!"
        )

    def show_level_down_notification(self):
        """Zeigt Level-Down Benachrichtigung"""
        QMessageBox.warning(None,
            "Level Down",
            f"Du bist auf Level {self.current_level} zurückgefallen."
        )
    def check_level_up(self):
        """Checks if conditions for level up are met and handles level changes"""
        if not self.period_start_date:
            return False
            
        today = datetime.now().date()
        days_passed = (today - self.period_start_date).days
        
        if days_passed >= 7:
            successful_days = self.count_successful_days()
            level_changed = False
            
            if successful_days >= 5:
                self.level_up()
                level_changed = True
            else:
                self.level_down()
                level_changed = True
                
            # Start new period
            self.period_start_date = today
            self.save_progress()
            return level_changed
            
        return False
    def show_level_progress_popup(self):
        """Zeigt den aktuellen Fortschritt zum nächsten Level"""
        remaining_days = 7 - (datetime.now().date() - self.period_start_date).days
        successful_days = self.count_successful_days()
        needed_days = 5 - successful_days
        
        if needed_days <= remaining_days:
            message = f"Noch {needed_days} Lerntage in den nächsten {remaining_days} Tagen bis zum nächsten Level."
        else:
            message = "Das Level-Ziel kann in diesem Zyklus nicht mehr erreicht werden."
        
        QMessageBox.information(None, "Level Fortschritt", message)

class HeatmapWidget(QWidget):
    def check_database(self):
        """Überprüft den Status der Datenbank"""
        try:
            cursor = self.db.conn.cursor()
        
            # Zähle alle Einträge
            cursor.execute("SELECT COUNT(*) FROM daily_stats")
            count = cursor.fetchone()[0]
        
            # Hole die letzten Einträge
            cursor.execute("""
                SELECT date, deck_id, cards_due, cards_studied, study_time 
                FROM daily_stats 
                ORDER BY date DESC
                LIMIT 5
            """)
            recent = cursor.fetchall()
        
            info_text = (f"Datenbankstatus:\n"
                        f"Anzahl Einträge: {count}\n\n"
                        f"Letzte Einträge:\n")
        
            for entry in recent:
                date, deck_id, due, studied, time = entry
                # Hole den Decknamen
                deck = next((d for d in mw.col.decks.all() if d['id'] == deck_id), None)
                deck_name = deck['name'] if deck else f"Unbekanntes Deck ({deck_id})"
                info_text += f"{date}: {studied} von {due} Karten in '{deck_name}'\n"
            
            showInfo(info_text)
        except Exception as e:
            showInfo(f"Datenbanktest fehlgeschlagen: {e}")

    def __init__(self, parent=None):
        super().__init__(parent)
        print("Study Tracker: Widget initialization started")
        
        # Konstanten für die Heatmap
        self.TOTAL_WEEKS = 29  # 203 Tage / 7 = 29 Wochen
        self.ROWS = self.TOTAL_WEEKS
        self.COLS = 7
        self.AUTO_SCROLL_ROW = self.ROWS - 3  # Drittletzte Zeile
        self.cell_size = 12
        
        # Initialisiere Datenbank und Deck-Auswahl
        self.db = Database()
        self.saved_deck = self.db.get_selected_deck()
        self.selected_deck = None if self.saved_deck == "Alle Stapel" else self.saved_deck
        
        # Initialize deck_id
        self.deck_id = None
        if self.selected_deck:
            deck = mw.col.decks.by_name(self.selected_deck)
            if deck:
                self.deck_id = deck['id']
        
        # Initialisiere Level-System
        self.level_system = LevelSystem(self.db, self.deck_id)
        
         # Setze Startdatum für die Heatmap
        self.today = datetime.now().date()  # Bereits ein date-Objekt
        offset_to_monday = self.today.weekday()
        self.start_date = self.today - timedelta(days=203 + offset_to_monday)  
        # Stelle sicher, dass installation_date ein date-Objekt ist
        self.installation_date = datetime.strptime(
            get_tracking_start_date(), 
            "%Y-%m-%d"
        ).date()
        
        # Display-Konfiguration
        screen = QApplication.primaryScreen()
        screen_width = screen.size().width()
        self.show_stats = screen_width > MOBILE_SCREEN_WIDTH
        
        # UI Setup
        self.setup_ui()
        self.update_stats_and_heatmap()
        
        self.setVisible(True)
        print("Study Tracker: Widget initialization completed")

    def setup_ui(self):
        print("Study Tracker: Setting up UI")
        self.setFixedWidth(200)
        self.setFixedHeight(550)
        self.setObjectName("mainWidget")
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Buttons Container
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setSpacing(3)
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        report_btn = QPushButton("Bericht")
        report_btn.setFixedSize(90, 22)
        report_btn.clicked.connect(self.show_report_dialog)
        
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
        
        self.level_label = QLabel(f"Level {self.level_system.current_level}")
        self.level_label.setStyleSheet("font-weight: bold; color: #388e3c;")
        level_layout.addWidget(self.level_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.week_progress_bar = QProgressBar()
        self.week_progress_bar.setFixedHeight(5)
        self.week_progress_bar.setTextVisible(False)  # Hier einfüge
        level_layout.addWidget(self.week_progress_bar)
        main_layout.addWidget(level_container)
        
        # Heatmap Bereich
        heatmap_container = QWidget()
        heatmap_layout = QVBoxLayout(heatmap_container)
        heatmap_layout.setContentsMargins(0, 5, 0, 5)
        heatmap_layout.setSpacing(2)
        
        # Wochentage
        days_container = QWidget()
        days_layout = QHBoxLayout(days_container)
        days_layout.setSpacing(4)
        days_layout.setContentsMargins(0, 0, 0, 0)
        
        for day in ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]:
            label = QLabel(day)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        
        # Stats Container
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
            
            # Refresh Button nach Stats
            refresh_btn = QPushButton("Aktualisieren")
            refresh_btn.clicked.connect(self.force_refresh)
            stats_layout.addWidget(refresh_btn)
            
            main_layout.addWidget(stats_container)
        
        main_layout.addStretch()

    def create_heatmap(self):
        """Erstellt die Heatmap-Visualisierung"""
        # Entferne alte Zellen
        for i in reversed(range(self.grid_layout.count())): 
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        # Nutze self.start_date statt neuem Startdatum
        for row in range(self.ROWS):
            for col in range(self.COLS):
                current_date = self.start_date + timedelta(days=row * 7 + col)
                
                # Prüfe, ob das Datum nach der Installation liegt
                intensity = 0  # Default grau
                if current_date >= self.installation_date and current_date <= self.today:
                    # current_date ist bereits ein date-Objekt, 
                    # also kein .date() nötig
                    intensity = self.get_day_intensity(current_date)
                
                is_today = current_date == self.today
                border_style = "1px solid black" if is_today else "none"
                
                cell = QFrame()
                cell.setFixedSize(self.cell_size, self.cell_size)
                cell.setStyleSheet(f"""
                    QFrame {{
                        background-color: {self.get_color_for_intensity(intensity)};
                        border: {border_style};
                        min-height: {self.cell_size}px;
                        max-height: {self.cell_size}px;
                        min-width: {self.cell_size}px;
                        max-width: {self.cell_size}px;
                    }}
                    QFrame:hover {{
                        border: 1px solid #000;
                    }}
                """)
                
                if current_date >= self.installation_date:
                    stats = self.get_day_stats(current_date)
                    tooltip = (
                        f"<b>{current_date.strftime('%d.%m.%Y')}</b><br>"
                        f"Fällige Karten: {stats['cards_due']}<br>"
                        f"Gelernte Karten: {stats['cards_studied']}<br>"
                        f"Lernzeit: {stats['study_time']} Minuten<br>"
                        f"Erfolgsquote: {stats['success_rate']}%"
                    )
                    cell.setToolTip(tooltip)
                
                self.grid_layout.addWidget(cell, row, col)
    
    def check_auto_scroll(self, current_date):
        """Prüft und führt Auto-Scroll durch wenn nötig"""
        needs_update = False
        while (current_date - self.start_date).days // 7 >= self.AUTO_SCROLL_ROW:
            self.start_date += timedelta(days=7)
            needs_update = True
        return needs_update
    
    def calculate_stats(self):
        """Berechnet die Statistiken ab dem Installationsdatum"""
        cursor = self.db.conn.cursor()
        start_date = get_tracking_start_date()
        
        try:
            # Berechne den Prozentsatz der Lerntage seit Installation
            cursor.execute("""
                WITH daterange AS (
                    SELECT ? as start_date, date('now') as end_date
                ),
                day_completion AS (
                    SELECT 
                        date,
                        CASE 
                            WHEN SUM(cards_due) = 0 THEN 1
                            WHEN SUM(cards_studied) >= SUM(cards_due) THEN 1
                            ELSE 0 
                        END as completed
                    FROM daily_stats
                    WHERE deck_id = ?
                    AND date >= ?
                    GROUP BY date
                )
                SELECT COALESCE(
                    COUNT(CASE WHEN completed = 1 THEN 1 END) * 100.0 / 
                    (JULIANDAY(end_date) - JULIANDAY(start_date) + 1),
                    0
                )
                FROM day_completion, daterange
            """, (start_date, self.deck_id, start_date))
            
            days_learned = round(cursor.fetchone()[0] or 0)
            
            # Rest der Funktion bleibt gleich...
            return {
                'days_learned': days_learned,
                'longest_streak': self.calculate_longest_streak(start_date),
                'current_streak': self.calculate_current_streak(start_date)
            }
                
        except Exception as e:
            print(f"Error calculating stats: {e}")
            return {
                'days_learned': 0,
                'longest_streak': 0,
                'current_streak': 0
            }
    def calculate_longest_streak(self, start_date):
        """Berechnet die längste Lernserie seit Installation"""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            WITH RECURSIVE dates(date) AS (
                SELECT ?
                UNION ALL
                SELECT date(date, '+1 day')
                FROM dates
                WHERE date < date('now')
            ),
            daily_status AS (
                SELECT 
                    d.date,
                    CASE 
                        WHEN SUM(ds.cards_due) = 0 THEN 1
                        WHEN SUM(ds.cards_studied) >= SUM(ds.cards_due) THEN 1
                        ELSE 0 
                    END as completed
                FROM dates d
                LEFT JOIN daily_stats ds ON d.date = ds.date AND ds.deck_id = ?
                GROUP BY d.date
            ),
            streaks AS (
                SELECT 
                    date,
                    completed,
                    SUM(CASE WHEN completed = 0 THEN 1 ELSE 0 END) 
                        OVER (ORDER BY date) as streak_group
                FROM daily_status
            )
            SELECT MAX(streak_length)
            FROM (
                SELECT COUNT(*) as streak_length
                FROM streaks
                WHERE completed = 1
                GROUP BY streak_group
            )
        """, (start_date, self.deck_id))
        return cursor.fetchone()[0] or 0

    def calculate_current_streak(self, start_date):
        """Berechnet die aktuelle Lernserie seit Installation"""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            WITH RECURSIVE dates(date) AS (
                SELECT date('now')
                UNION ALL
                SELECT date(date, '-1 day')
                FROM dates
                WHERE date >= ?
            ),
            daily_status AS (
                SELECT 
                    d.date,
                    CASE 
                        WHEN SUM(ds.cards_due) = 0 THEN 1
                        WHEN SUM(ds.cards_studied) >= SUM(ds.cards_due) THEN 1
                        ELSE 0 
                    END as completed
                FROM dates d
                LEFT JOIN daily_stats ds ON d.date = ds.date AND ds.deck_id = ?
                GROUP BY d.date
                ORDER BY d.date DESC
            )
            SELECT COUNT(*)
            FROM daily_status
            WHERE completed = 1
            AND date >= (
                SELECT MIN(date)
                FROM daily_status
                WHERE completed = 0
                UNION
                SELECT MIN(date) FROM daily_status
                ORDER BY date DESC
                LIMIT 1
            )
        """, (start_date, self.deck_id))
        return cursor.fetchone()[0] or 0
    
    def get_day_intensity(self, date):
        # Änderung: Entferne .date() da date bereits ein datetime.date Objekt ist
        if date > datetime.now().date():
            return 0  # Grau für zukünftige Tage
        
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
        cursor = self.db.conn.cursor()
        
        # Für vergangene Tage
        query = """
            SELECT SUM(cards_due) as total_due, 
                SUM(cards_studied) as total_studied, 
                SUM(study_time) as total_time
            FROM daily_stats 
            WHERE date = ?
        """
        
        params = [date.strftime("%Y-%m-%d")]
        
        # Füge deck_id Filter hinzu wenn ein Deck ausgewählt ist
        if self.deck_id:
            query += " AND deck_id = ?"
            params.append(self.deck_id)
            
        cursor.execute(query, params)
        row = cursor.fetchone()
        
        if not row or all(v is None for v in row):
            return self.get_empty_stats()
        
        cards_due = row[0] or 0
        cards_studied = row[1] or 0
        study_time = row[2] or 0
        
        success_rate = 100 if cards_due == 0 else (cards_studied / cards_due * 100)
        
        return {
            'cards_due': cards_due,
            'cards_studied': cards_studied,
            'study_time': study_time,
            'success_rate': round(success_rate, 1)
        }

    def get_empty_stats(self):
        """Gibt leere Statistiken zurück"""
        return {
            'cards_due': 0,
            'cards_studied': 0,
            'study_time': 0,
            'success_rate': 0
        }

    def show_report_dialog(self):
        """Zeigt den Dialog zur Berichtserstellung an"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Berichtszeitraum auswählen")
        dialog.setStyleSheet("QWidget { background-color: #f9f9f9; }")
        
        layout = QVBoxLayout(dialog)
        date_layout = QGridLayout()
        
        start_date = QDateEdit()
        start_date.setDate(QDate.currentDate().addDays(-30))
        end_date = QDateEdit()
        end_date.setDate(QDate.currentDate())
        
        date_layout.addWidget(QLabel("Von:"), 0, 0)
        date_layout.addWidget(start_date, 0, 1)
        date_layout.addWidget(QLabel("Bis:"), 1, 0)
        date_layout.addWidget(end_date, 1, 1)
        
        layout.addLayout(date_layout)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(lambda: self.export_report(start_date.date(), end_date.date()))
        buttons.rejected.connect(dialog.reject)
        
        layout.addWidget(buttons)
        dialog.exec()

    def export_report(self, start_date, end_date):
        """Exportiert den Bericht für den gewählten Zeitraum"""
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Bericht speichern",
            "",
            "HTML Dateien (*.html);;Alle Dateien (*.*)"
        )
        
        if file_name:
            try:
                html_content = self.generate_detailed_report(
                    start_date.toString("yyyy-MM-dd"), 
                    end_date.toString("yyyy-MM-dd")
                )
                with open(file_name, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                
                QMessageBox.information(
                    self,
                    "Erfolg",
                    f"Bericht wurde erfolgreich gespeichert unter:\n{file_name}"
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Fehler",
                    f"Fehler beim Speichern des Berichts:\n{str(e)}"
                )

    def generate_detailed_report(self, start_date, end_date):
        """Generiert einen detaillierten HTML-Bericht"""
        cursor = self.db.conn.cursor()
        
        # Konvertiere die Datumsstrings in deutsches Format
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        start_date_formatted = start_date_obj.strftime("%d.%m.%Y")
        end_date_formatted = end_date_obj.strftime("%d.%m.%Y")
        
        # Hole Level-Historie
        level_changes = cursor.execute("""
            SELECT change_date, change_type, old_level, new_level
            FROM level_history
            WHERE deck_id = ?
            AND date(change_date) BETWEEN ? AND ?
            ORDER BY change_date
        """, (self.deck_id, start_date, end_date)).fetchall()
        
        # Hole tägliche Statistiken
        daily_stats = cursor.execute("""
            SELECT date, cards_due, cards_studied, study_time
            FROM daily_stats
            WHERE deck_id = ?
            AND date BETWEEN ? AND ?
            ORDER BY date DESC
        """, (self.deck_id, start_date, end_date)).fetchall()
        
        # Hole Validierungscodes und Chat-Links
        validation_data = cursor.execute("""
            SELECT date, code, page_number, chat_link
            FROM validation_codes
            WHERE deck_id = ?
            AND date BETWEEN ? AND ?
            ORDER BY date DESC
        """, (self.deck_id, start_date, end_date)).fetchall()
        
        # Berechne Zusammenfassungen
        total_days = len(daily_stats)
        successful_days = len([d for d in daily_stats if d[2] >= d[1]])
        tasks_completed = len(validation_data)
        
        # Erstelle Highcharts-Diagramm für Level-Verlauf
        level_chart_data = self.prepare_level_chart_data(level_changes)
        
        # Generiere HTML mit Tailwind CSS
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width">
            <title>Lernbericht</title>
            <script src="https://code.highcharts.com/highcharts.js"></script>
            <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
        </head>
        <body class="bg-gray-50">
            <div class="container mx-auto px-4 py-8">
                <h1 class="text-3xl font-bold mb-2">Lernbericht</h1>
                <p class="text-gray-600 mb-8">vom {start_date_formatted} bis zum {end_date_formatted}</p>
                <p class="text-gray-600 mb-8">Stapel: {self.selected_deck if self.selected_deck else "Alle Stapel"}</p>
                
                <!-- Zusammenfassung -->
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
                    <div class="bg-white p-6 rounded-lg shadow">
                        <h3 class="text-lg font-semibold mb-2">Erfolgreiche Lerntage</h3>
                        <p class="text-2xl">{successful_days}/{total_days}</p>
                    </div>
                    <div class="bg-white p-6 rounded-lg shadow">
                        <h3 class="text-lg font-semibold mb-2">Aktuelles Level</h3>
                        <p class="text-2xl">{self.level_system.current_level}</p>
                    </div>
                    <div class="bg-white p-6 rounded-lg shadow">
                        <h3 class="text-lg font-semibold mb-2">Bearbeitete Aufgaben</h3>
                        <p class="text-2xl">{tasks_completed}</p>
                    </div>
                </div>
                
                <!-- Level-Verlauf Chart -->
                <div class="bg-white p-6 rounded-lg shadow mb-8">
                    <h2 class="text-xl font-bold mb-4">Level-Verlauf</h2>
                    <div id="levelChart" style="height: 300px;"></div>
                </div>
                
                    <!-- Validierungscodes und Chat-Links -->
                <div class="bg-white rounded-lg shadow overflow-hidden mb-8">
                    <div class="px-6 py-4 border-b">
                        <h2 class="text-xl font-bold">Bearbeitete Aufgaben</h2>
                    </div>
                    <table class="min-w-full">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Datum</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Code</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Chat</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
        """
        
        for data in validation_data:
            date, code, page, link = data
            formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
            html_content += f"""
                <tr>
                    <td class="px-6 py-4">{formatted_date}</td>
                    <td class="px-6 py-4">{code}</td>
                    <td class="px-6 py-4">{page}</td>
                    <td class="px-6 py-4">
                        <a href="{link}" target="_blank" class="text-blue-600 hover:underline">Öffnen</a>
                    </td>
                </tr>
            """
        
        html_content += """
                        </tbody>
                    </table>
                </div>
                
                <!-- Tägliche Statistiken -->
                <div class="bg-white rounded-lg shadow overflow-hidden">
                    <div class="px-6 py-4 border-b">
                        <h2 class="text-xl font-bold">Tägliche Statistiken</h2>
                    </div>
                    <table class="min-w-full">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Datum</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Fällige Karten</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Gelernte Karten</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
        """
        
        for stats in daily_stats:
            date, due, studied, time = stats
            formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
            success = "✓" if studied >= due else "×"
            success_class = "text-green-600" if studied >= due else "text-red-600"
            
            html_content += f"""
                <tr>
                    <td class="px-6 py-4">{formatted_date}</td>
                    <td class="px-6 py-4">{due}</td>
                    <td class="px-6 py-4">{studied}</td>
                    <td class="px-6 py-4 {success_class}">{success}</td>
                </tr>
            """
        
        html_content += """
                        </tbody>
                    </table>
                </div>
            </div>
            
            <script>
                Highcharts.chart('levelChart', {
                    chart: { type: 'line' },
                    title: { text: 'Level-Entwicklung' },
                    xAxis: { type: 'datetime' },
                    yAxis: { 
                        title: { text: 'Level' },
                        min: 1
                    },
                    series: [{
                        name: 'Level',
                        data: """ + level_chart_data + """
                    }]
                });
            </script>
        </body>
        </html>
        """
        
        return html_content
        
    def prepare_level_chart_data(self, level_changes):
        """Bereitet die Level-Daten für Highcharts auf"""
        try:
            data = []
            current_level = 1
            
            for change in level_changes:
                date = datetime.strptime(change[0], "%Y-%m-%d %H:%M:%S")
                timestamp = int(date.timestamp() * 1000)
                current_level = change[3]
                data.append([timestamp, current_level])
            
            return json.dumps(data)
        except Exception as e:
            print(f"Error preparing chart data: {e}")
            return "[]"  # Leeres Array als Fallback

    def show_deck_selector(self):
        """Zeigt den Dialog zur Deck-Auswahl"""
        dialog = DeckSelectorDialog(self, self.selected_deck)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = dialog.deck_list.currentItem().text()
            self.selected_deck = None if selected == "Alle Stapel" else selected
            
            # Update deck_id when deck selection changes
            self.deck_id = None
            if self.selected_deck:
                deck = mw.col.decks.by_name(self.selected_deck)
                if deck:
                    self.deck_id = deck['id']
            
            self.db.save_selected_deck(selected)
            # Reinitialize level system with new deck_id
            self.level_system = LevelSystem(self.db, self.deck_id)
            self.update_stats_and_heatmap()

    def check_streak_record(self):
        """Überprüft, ob ein neuer Streak-Rekord erreicht wurde"""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT record FROM streak_records ORDER BY record DESC LIMIT 1
        """)
        old_record = cursor.fetchone()
        current_streak = self.calculate_stats()['current_streak']
        
        if not old_record or current_streak > old_record[0]:
            cursor.execute("""
                INSERT INTO streak_records (record, date) 
                VALUES (?, ?)
            """, (current_streak, datetime.now().strftime("%Y-%m-%d")))
            self.db.conn.commit()
            return True
        return False

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
        
        layout.addWidget(emoji_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(days_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        animation_widget.setFixedSize(180, 100)
        animation_widget.move(self.width(), 10)
        animation_widget.show()
        
        slide_in = QPropertyAnimation(animation_widget, b"pos")
        slide_in.setDuration(800)
        slide_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        end_x = self.width() - animation_widget.width() - 20
        
        slide_in.setStartValue(QPoint(self.width(), 10))
        slide_in.setEndValue(QPoint(end_x, 10))
        
        slide_out = QPropertyAnimation(animation_widget, b"pos")
        slide_out.setDuration(800)
        slide_out.setEasingCurve(QEasingCurve.Type.InCubic)
        slide_out.setStartValue(QPoint(end_x, 10))
        slide_out.setEndValue(QPoint(self.width(), 10))
        
        slide_out.finished.connect(animation_widget.deleteLater)
        
        slide_in.start()
        
        QTimer.singleShot(2500, slide_out.start)

    def show_level_up_animation(self):
        """Zeigt eine Animation für ein Level-Up"""
        celebration = QMessageBox(self)
        celebration.setWindowTitle("Level Up!")
        celebration.setText(f"Glückwunsch! Du hast Level {self.level_system.current_level} erreicht!")
        celebration.setIcon(QMessageBox.Icon.Information)
        celebration.setStandardButtons(QMessageBox.StandardButton.Ok)
        celebration.show()

    def show_status_message(self, message):
        """Zeigt eine Statusnachricht an"""
        QMessageBox.information(self, "Status Update", message)

    def update_stats_and_heatmap(self):
        """Aktualisiert alle Statistiken und die Heatmap"""
        save_daily_stats()
        
        today = datetime.now().date()
        # Prüfe Auto-Scroll
        needs_update = self.check_auto_scroll(today)
        
        # Aktualisiere Heatmap wenn nötig
        if needs_update:
            self.create_heatmap()
        
        # Diese Updates immer durchführen
        week_progress = self.level_system.calculate_weekly_progress()
        self.week_progress_bar.setValue(int(week_progress))
        
        if self.level_system.check_level_up():
            self.show_level_up_animation()
            
        self.level_label.setText(f"Level {self.level_system.current_level}")
        
        if self.show_stats:
            stats = self.calculate_stats()
            self.update_stats(stats)

    def update_stats(self, stats):
        """Aktualisiert die Statistik-Labels"""
        if not self.show_stats:
            return
            
        self.stats_labels['days_learned'].setText(f"Gelernt an: {stats['days_learned']}% der Tage")
        self.stats_labels['longest_streak'].setText(f"Längste Serie: {stats['longest_streak']} Tage")
        self.stats_labels['current_streak'].setText(f"Aktuelle Serie: {stats['current_streak']} Tage")
        
        if stats['current_streak'] > 0 and self.check_streak_record():
            self.show_streak_record_animation(stats['current_streak'])

    def force_refresh(self):
        """Erzwingt eine komplette Aktualisierung aller Statistiken"""
        print("Study Tracker: Forcing refresh")
        save_daily_stats()  # Speichere aktuelle Statistiken
        self.create_heatmap()  # Direkte Neuerstellung der Heatmap
        self.update_stats_and_heatmap()  # Aktualisiere übrige Statistiken
        QApplication.processEvents()  # Verarbeite ausstehende UI-Events

    def closeEvent(self, event):
        """Event beim Schließen des Widgets"""
        save_daily_stats()  # Speichere Statistiken vor dem Schließen
        self.db.close()
        super().closeEvent(event)

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
                QLineEdit.Password
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
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Warnung")
        msg.setText("Beim Import werden alle aktuellen Daten überschrieben!")
        msg.setInformativeText("Möchten Sie fortfahren?")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        
        if msg.exec() == QMessageBox.Yes:
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
                    QLineEdit.Password
                )
                
                if ok:  # User clicked OK
                    if self.db.import_backup(file_name, password if password else None):
                        QMessageBox.information(
                            self,
                            "Erfolg",
                            "Daten wurden erfolgreich importiert."
                        )
                        self.update_stats_and_heatmap()
                    else:
                        QMessageBox.critical(
                            self,
                            "Fehler",
                            "Daten konnten nicht importiert werden.\nFalsches Passwort?"
                        )


class DeckSelectorDialog(QDialog):
    """Dialog zur Deck-Auswahl"""
    def __init__(self, parent=None, selected_deck=None):
        super().__init__(parent)
        self.setWindowTitle("Stapel auswählen")
        self.setStyleSheet("background-color: #f9f9f9;")

        layout = QVBoxLayout(self)
        
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
        
        self.deck_list.addItem("Alle Stapel")
        for deck in mw.col.decks.all():
            self.deck_list.addItem(deck['name'])
        
        if selected_deck:
            items = self.deck_list.findItems(selected_deck, Qt.MatchFlag.MatchExactly)
            if items:
                items[0].setSelected(True)
                self.deck_list.setCurrentItem(items[0])
        else:
            self.deck_list.item(0).setSelected(True)
            self.deck_list.setCurrentItem(self.deck_list.item(0))
        
        layout.addWidget(self.deck_list)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

def create_widget():
    """Erstellt das Hauptwidget"""
    try:
        if not mw or not mw.col:
            print("Study Tracker: Main window or collection not ready")
            return False
            
        if hasattr(mw, 'study_tracker_widget'):
            print("Study Tracker: Widget already exists")
            return True
            
        print("Study Tracker: Creating widget...")
        
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
        mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        
        # Stelle sicher, dass das Dock Widget sichtbar ist
        dock.setVisible(True)
        widget.setVisible(True)
        
        # Platziere das Widget am rechten Rand
        mw.resizeDocks([dock], [200], Qt.Orientation.Horizontal)
        
        # Speichere Referenzen
        mw.study_tracker_widget = widget
        mw.study_tracker_dock = dock
        
        print("Study Tracker: Widget created successfully")
        
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
        
        return True
        
    except Exception as e:
        print(f"Study Tracker: Error initializing widget: {e}")
        import traceback
        traceback.print_exc()
        return False

def debug_database():
    """Überprüft den aktuellen Datenbankinhalt"""
    try:
        db = Database()
        cursor = db.conn.cursor()
        
        print("\nStudy Tracker: Current Database Content")
        print("=====================================")
        
        # Prüfe daily_stats
        cursor.execute("SELECT * FROM daily_stats ORDER BY date DESC LIMIT 5")
        stats = cursor.fetchall()
        print("\nLatest daily_stats entries:")
        for stat in stats:
            print(f"Date: {stat[0]}, Deck: {stat[1]}, Due: {stat[2]}, Studied: {stat[3]}, Time: {stat[4]}")
            
        # Prüfe level_progress
        cursor.execute("SELECT * FROM level_progress ORDER BY last_updated DESC LIMIT 1")
        level = cursor.fetchone()
        if level:
            print(f"\nCurrent level progress:")
            print(f"Level: {level[1]}, Start Date: {level[2]}, Weeks: {level[3]}, Updated: {level[4]}")
            
        db.close()
    except Exception as e:
        print(f"Error in debug_database: {e}")

# Füge diese Zeile am Ende von on_review hinzu:
debug_database()

def handle_validation_code(deck_id, code, page_number, chat_link):
    """Behandelt die Speicherung eines Validierungscodes"""
    try:
        db = Database()
        result = db.save_validation_code(deck_id, code, page_number, chat_link)
        return "success" if result else "error"
    except Exception as e:
        print(f"Error handling validation code: {e}")
        return "error"
    finally:
        db.close()

def refresh_stats():
    """Separate Funktion für UI-Aktualisierung"""
    try:
        print("Study Tracker: Starting widget refresh...")
        if hasattr(mw, 'study_tracker_widget'):
            mw.study_tracker_widget.force_refresh()
            print("Study Tracker: Widget refresh complete")
        else:
            print("Study Tracker: Widget not found during refresh")
    except Exception as e:
        print(f"Study Tracker: Error during refresh: {e}")
        traceback.print_exc()

def test_db():
    try:
        # Prüfe ob Anki bereit ist
        if not mw.col:
            showInfo("Datenbank kann nicht getestet werden: Anki noch nicht bereit")
            return
            
        db = Database()
        cursor = db.conn.cursor()
        
        # Zähle alle Einträge
        cursor.execute("SELECT COUNT(*) FROM daily_stats")
        count = cursor.fetchone()[0]
        
        # Hole die letzten Einträge
        cursor.execute("""
            SELECT date, deck_id, cards_due, cards_studied, study_time 
            FROM daily_stats 
            ORDER BY date DESC
            LIMIT 5
        """)
        recent = cursor.fetchall()
        
        info_text = (f"Datenbankstatus:\n"
                    f"Anzahl Einträge: {count}\n\n"
                    f"Letzte Einträge:\n")
        
        if recent:
            for entry in recent:
                date, deck_id, due, studied, time = entry
                # Sichere Deck-Name Ermittlung
                try:
                    deck = mw.col.decks.get(deck_id)
                    deck_name = deck.get('name', f'Unbekanntes Deck ({deck_id})')
                except:
                    deck_name = f'Unbekanntes Deck ({deck_id})'
                
                info_text += f"{date}: {studied} von {due} Karten in '{deck_name}'\n"
        else:
            info_text += "Keine Einträge gefunden"
            
        showInfo(info_text)
        db.close()
    except Exception as e:
        showInfo(f"Datenbanktest fehlgeschlagen: {e}")

def delayed_setup():
    """Verbesserte verzögerte Initialisierung mit Clean Start"""
    print("Study Tracker: Checking Anki readiness...")
    
    if not mw or not mw.col:
        print("Study Tracker: Anki not ready, scheduling retry...")
        QTimer.singleShot(1000, delayed_setup)
        return
    
    try:
        print("Study Tracker: Initializing clean start...")
        initialize_clean_start()
        
        print("Study Tracker: Creating widget...")
        if create_widget():
            print("Study Tracker: Setup completed successfully")
            mw.study_tracker_widget.level_system.show_level_progress_popup()  # Hier einfügen
            
            # Erzwinge Layout-Update
            mw.centralWidget().setVisible(False)
            mw.centralWidget().setVisible(True)
        else:
            print("Study Tracker: Widget creation failed, scheduling retry...")
            QTimer.singleShot(1000, delayed_setup)
            
    except Exception as e:
        print(f"Study Tracker: Setup error: {e}")
        traceback.print_exc()
        QTimer.singleShot(1000, delayed_setup)
    
    check_updates()

def on_review():
    """Hook für die Aktualisierung nach einer Kartenwiederholung"""
    print("\nStudy Tracker: Review detected!")
    if hasattr(mw, 'study_tracker_widget'):
        try:
            print("Study Tracker: Saving stats...")
            save_daily_stats()  # Speichere aktuelle Statistiken
            
            # Verwende QTimer.singleShot für verzögerte Aktualisierung
            QTimer.singleShot(100, lambda: update_widget_safely())
            
            debug_database()
        except Exception as e:
            print(f"Study Tracker: Error in on_review: {e}")
            traceback.print_exc()
    else:
        print("Study Tracker: Widget not found!")

def update_widget_safely():
    """Sichere Aktualisierung des Widgets"""
    try:
        if hasattr(mw, 'study_tracker_widget'):
            print("Study Tracker: Updating widget...")
            widget = mw.study_tracker_widget
            
            # Aktualisiere Level und Fortschritt
            widget.level_label.setText(f"Level {widget.level_system.current_level}")
            progress = widget.level_system.calculate_weekly_progress()
            widget.week_progress_bar.setValue(int(progress))
            
            # Aktualisiere Heatmap
            widget.create_heatmap()
            
            # Aktualisiere Statistiken wenn vorhanden
            if widget.show_stats and hasattr(widget, 'stats_labels'):
                stats = widget.calculate_stats()
                widget.update_stats(stats)
            
            # Erzwinge UI-Update
            QApplication.processEvents()
            
            print("Study Tracker: Widget update complete")
    except Exception as e:
        print(f"Study Tracker: Error updating widget: {e}")
        traceback.print_exc()

# Registriere den Review-Hook
addHook("reviewDidEase", on_review)

# Starte die Initialisierung
print("Study Tracker: Starting initialization...")
QTimer.singleShot(3000, delayed_setup)
