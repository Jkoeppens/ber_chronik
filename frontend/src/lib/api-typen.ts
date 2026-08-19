/**
 * api-typen.ts — ERZEUGT. Nicht von Hand bearbeiten.
 *
 * Quelle ist das OpenAPI-Schema des Servers, also src/neu/modelle.py.
 * Neu erzeugen, mit laufendem Server (uvicorn src.neu.server:app --port 8002):
 *
 *     npm run typen
 *
 * Die Datei wird committet, damit ein Build ohne laufenden Server durchläuft.
 * Wer hier von Hand ändert, verliert es beim nächsten Lauf — und schlimmer:
 * die Typen behaupten dann etwas, das der Server nicht liefert. Gewollt ist
 * das Gegenteil: benennt jemand ein Feld in modelle.py um, soll der Build
 * scheitern und die Stelle nennen.
 */

export interface paths {
    "/api/konfiguration": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Konfiguration
         * @description Was gerade eingestellt ist: Anbieter, Modelle, Schwellen.
         *
         *     Dieselbe Auskunft wie beim Hochfahren, nur abrufbar. Von Schlüsseln steht
         *     hier nur, ob sie gesetzt sind — nie ihr Wert, und keine Projekt-Token.
         */
        get: operations["konfiguration_api_konfiguration_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekte": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Projekte
         * @description Alle Projekte mit ihren Zahlen, nach Anlagedatum.
         *
         *     anzahl_einheiten ist COUNT(*), der Zeitraum MIN/MAX über die Einheiten —
         *     beides gerechnet, nichts aus einer Konfigurationsdatei.
         */
        get: operations["projekte_api_projekte_get"];
        put?: never;
        /**
         * Projekt Anlegen
         * @description Legt ein leeres Projekt an.
         *
         *     Eigentümer ist der lokale Zugang (siehe src/neu/projekte.py). Sobald es
         *     eine Anmeldung gibt, wird daraus ein echter — die Zeilen hängen dann nur
         *     umzuhängen.
         */
        post: operations["projekt_anlegen_api_projekte_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/kennzahlen": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Projekt Kennzahlen
         * @description Was in der Datenbank steht: Einheiten, Datierung, Kategorien, Akteure.
         *
         *     Alles gerechnet. Dazu die letzten zwanzig Läufe, damit sichtbar ist, was
         *     schon gelaufen ist und was noch nicht.
         */
        get: operations["projekt_kennzahlen_api_projekt__projekt_id__kennzahlen_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Projekt
         * @description Ein Projekt.
         */
        get: operations["projekt_api_projekt__projekt_id__get"];
        put?: never;
        post?: never;
        /**
         * Projekt Loeschen
         * @description Löscht ein Projekt samt allem, was daran hängt.
         *
         *     Quellen, Einheiten, Kategorien, Akteure und Läufe gehen über
         *     ON DELETE CASCADE mit. Die Exportdateien unter data/projects/ bleiben
         *     liegen — sie sind ein Erzeugnis, kein Bestandteil des Projekts, und
         *     Dateien zu löschen ist nicht Sache dieses Endpoints.
         */
        delete: operations["projekt_loeschen_api_projekt__projekt_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/einheiten": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Einheiten
         * @description Alle Einheiten eines Projekts, nach Quelle und Position sortiert.
         *
         *     Unbekanntes Projekt → 404. Bekanntes Projekt ohne Treffer → 200, leere Liste.
         */
        get: operations["einheiten_api_projekt__projekt_id__einheiten_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/quelle": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Quelle Anlegen
         * @description Liest eine Quelle ein und legt quelle, einheit und lauf an.
         *
         *     Ein DOCX kommt aus data/raw/ — dorthin legt der Upload es ab, und ein Pfad
         *     aus dem Netz darf nicht ins übrige Dateisystem zeigen.
         *
         *     Ein Obsidian-Ordner liegt dort nie: er liegt in Dropbox oder als
         *     absoluter Pfad auf der Platte, etwa unter ~/Library/CloudStorage/. Für
         *     Sammlungen gilt die data/raw/-Bindung deshalb nicht — geprüft wird, dass
         *     der Pfad ein vorhandenes Verzeichnis ist.
         */
        post: operations["quelle_anlegen_api_projekt__projekt_id__quelle_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/klassifizieren": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Projekt Klassifizieren
         * @description Stößt die Klassifikation an und kommt sofort zurück.
         *
         *     Das Embedding aller Einheiten dauert; den Stand liefert GET /api/lauf/{id}.
         *     Handkorrekturen (kategorie_herkunft='manuell') bleiben bei 'offen' und
         *     'alle' unberührt.
         */
        post: operations["projekt_klassifizieren_api_projekt__projekt_id__klassifizieren_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/einheit/{einheit_id}/kategorie": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Kategorie Von Hand Setzen
         * @description Setzt die Kategorie einer Einheit von Hand.
         *
         *     Die Zuordnung gilt danach als 'manuell' und bleibt bei Neuläufen unberührt;
         *     die Konfidenz wird geleert, weil sie ein maschinelles Urteil beschrieb.
         */
        patch: operations["kategorie_von_hand_setzen_api_einheit__einheit_id__kategorie_patch"];
        trace?: never;
    };
    "/api/lauf/{lauf_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Lauf Stand
         * @description Der Stand eines Schritts — so oft abfragbar, wie man mag.
         *
         *     Kein Strom, keine Sentinels: der Fortschritt steht in der lauf-Zeile und
         *     überlebt eine abgerissene Verbindung wie einen neu geladenen Reiter.
         */
        get: operations["lauf_stand_api_lauf__lauf_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/taxonomie/vorschlagen": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Taxonomie Vorschlagen
         * @description Stößt den Taxonomielauf an und kommt sofort zurück.
         *
         *     warm_start=false: neu vorschlagen, n_clusters wählbar.
         *     warm_start=true : verfeinern, n_clusters ist die Anzahl der vorhandenen.
         *
         *     Der Lauf dauert Minuten. Deshalb 202 mit einer lauf_id statt einer Antwort,
         *     auf die man wartet — den Stand liefert GET /api/lauf/{id}.
         */
        post: operations["taxonomie_vorschlagen_api_projekt__projekt_id__taxonomie_vorschlagen_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/datieren": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Projekt Datieren
         * @description Datiert die Einheiten eines Projekts, Quelle für Quelle.
         *
         *     Handkorrekturen bleiben bei 'offen' und 'alle' unberührt; 'auch_manuell'
         *     überschreibt sie. Zeigt eine Handkorrektur ins Leere, steht das als
         *     Warnung in der Antwort — nicht stillschweigend nichts.
         */
        post: operations["projekt_datieren_api_projekt__projekt_id__datieren_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/einheit/{einheit_id}/datierung": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Datierung Von Hand Setzen
         * @description Setzt die Datierung einer Einheit von Hand.
         *
         *     datum_von leer heißt undatierbar, datum_bis leer heißt Zeitpunkt. Die
         *     Korrektur wird eine anker-Zeile mit herkunft='manuell' und überlebt jeden
         *     Neulauf außer 'auch_manuell' — samt ihrer Genauigkeit und ihrer Begründung.
         */
        patch: operations["datierung_von_hand_setzen_api_einheit__einheit_id__datierung_patch"];
        trace?: never;
    };
    "/api/einheit/{einheit_id}/text": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Einheit Text Setzen
         * @description Ändert den Wortlaut einer Einheit und räumt auf, was daran hing.
         *
         *     Die Akteursfundstellen dieser Einheit werden gelöscht — ihre Zeichen-
         *     positionen zeigten danach auf andere Wörter, und eine falsche Markierung
         *     ist schlimmer als eine fehlende. Der nächste Akteurslauf legt sie neu an.
         *     Die Anker werden neu abgeleitet, indem die Datierung noch einmal läuft
         *     (Umfang 'alle', Handkorrekturen bleiben).
         */
        patch: operations["einheit_text_setzen_api_einheit__einheit_id__text_patch"];
        trace?: never;
    };
    "/api/projekt/{projekt_id}/datierung": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Datierung Verteilung
         * @description Woher die Daten kommen, wo die Ausreißer sitzen, und die Belege je Einheit.
         *
         *     Die Belege sind der Unterschied zur alten Vorschau: dort stand das
         *     Ergebnis, hier steht, was es ausgelöst hat. Ein Datum 3012 ist damit als
         *     Zifferndreher in der Quellennotation erkennbar und nicht als Rechenfehler.
         */
        get: operations["datierung_verteilung_api_projekt__projekt_id__datierung_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/akteure/erkennen": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Akteure Erkennen
         * @description Erkennt die Akteure eines Projekts und ordnet sie den Einheiten zu.
         *
         *     Akteure mit herkunft='manuell' bleiben unberührt, abgelehnte filtern den
         *     Fehlfund erneut heraus. Verschmelzungskandidaten werden dabei neu berechnet.
         */
        post: operations["akteure_erkennen_api_projekt__projekt_id__akteure_erkennen_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/akteur/{akteur_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Akteur Von Hand Aendern
         * @description Ändert einen Akteur von Hand.
         *
         *     Der Akteur gilt danach als 'manuell' und bleibt bei Neuläufen unberührt.
         *     Ändern sich Normalform oder Aliase, werden die Fundstellen sofort neu
         *     abgeleitet — nicht erst beim nächsten Lauf.
         */
        patch: operations["akteur_von_hand_aendern_api_akteur__akteur_id__patch"];
        trace?: never;
    };
    "/api/akteure/verschmelzen": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Akteure Zusammenlegen
         * @description Führt beliebige Akteure zu einem zusammen.
         *
         *     behalten_id bestimmt, welche Normalform stehen bleibt; alle übrigen Namen
         *     werden zu Aliasen. Ein vorgeschlagenes Paar muss es nicht sein.
         */
        post: operations["akteure_zusammenlegen_api_akteure_verschmelzen_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/akteure/duplikatskandidaten": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Akteure Duplikatskandidaten
         * @description Die gespeicherten Verschmelzungskandidaten eines Projekts.
         *
         *     Gelesen, nicht gerechnet: berechnet werden sie beim Erkennungslauf, aus
         *     einer Quelle mit drei Regeln — Alias-Überschneidung, Schreibweise,
         *     Ähnlichkeit im Band unterhalb der Schwelle.
         */
        get: operations["akteure_duplikatskandidaten_api_projekt__projekt_id__akteure_duplikatskandidaten_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/exportieren": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Projekt Exportieren
         * @description Erzeugt die Dateien, die viz/ liest — gleiche Namen, gleiches Format.
         *
         *     Der Zeitraum in project_meta.json ist MIN(jahr_von) bis MAX(jahr_bis) über
         *     die Einheiten, keine gespeicherte Angabe. Undatierte Einheiten stehen in
         *     data.json und fehlen nur auf der Zeitachse; wie viele es sind, sagt
         *     anzahl_ohne_datum.
         */
        post: operations["projekt_exportieren_api_projekt__projekt_id__exportieren_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/quelle/datei": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Quelle Hochladen
         * @description Nimmt eine Datei aus dem Browser entgegen, legt sie in data/raw/ ab und
         *     liest sie ein.
         *
         *     Der Dateiname kommt vom Client und wird nicht geglaubt: nur der Basisname
         *     zählt, und der muss unterhalb von data/raw/ landen. Eine vorhandene Datei
         *     wird nicht überschrieben — sonst könnte ein Upload eine fremde Quelle
         *     austauschen, an der schon ein Projekt hängt.
         *
         *     Für Obsidian bleibt es ein Ordnerpfad: dafür ist POST …/quelle da.
         */
        post: operations["quelle_hochladen_api_projekt__projekt_id__quelle_datei_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/kategorien": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Kategorien Liste
         * @description Die Kategorien eines Projekts mit der Zahl der Einheiten darauf.
         *
         *     Dazu, wie viele Einheiten beim nächsten Zuordnen erst embeddet werden
         *     müssen: die Fläche soll eine Dauer nur ankündigen, wenn es eine gibt. Steht
         *     kein Anbieter, ist die Frage nicht zu beantworten — dann null statt einer
         *     geratenen Zahl, und der Lauf scheitert später ohnehin mit 503.
         */
        get: operations["kategorien_liste_api_projekt__projekt_id__kategorien_get"];
        /**
         * Kategorien Speichern
         * @description Speichert die ganze Kategorienliste und ordnet danach neu zu.
         *
         *     Beides gehört zusammen: eine geänderte Beschreibung ändert, wohin die
         *     Einheiten gehören. Es getrennt zu lassen hieße, einen Zustand zu erlauben,
         *     in dem die Zuordnung zu Beschreibungen passt, die es nicht mehr gibt.
         *
         *     Warum 202 und ein Lauf, obwohl das Zuordnen mit gefüllten Vektoren in etwa
         *     einer Sekunde durch ist: die Ausnahmen sind zu regelmäßig für einen
         *     gewöhnlichen Klick. Beim ersten Speichern nach dem Ingest ist der Speicher
         *     leer (12 bis 31 Sekunden je nach Projektgröße), nach einem Serverneustart
         *     liegt das Modell nicht im Arbeitsspeicher (weitere 12), und ein
         *     Anbieterwechsel entwertet alles auf einmal. Ein Klick, der meistens eine
         *     Sekunde dauert und ab und zu eine halbe Minute, ist schlechter als einer,
         *     der immer denselben Weg nimmt.
         *
         *     Was stattdessen aufhört: die Fläche kündigt eine Dauer nur an, wenn
         *     einheiten_ohne_vektor aus GET …/kategorien größer als null ist.
         *
         *     Eine leere Liste ist ein gültiger Sollzustand — alle Kategorien weg — und
         *     hängt keinen Lauf an: es gibt nichts, wogegen zugeordnet werden könnte.
         *     Dann kommt lauf_id null zurück.
         */
        put: operations["kategorien_speichern_api_projekt__projekt_id__kategorien_put"];
        /**
         * Kategorie Anlegen
         * @description Legt eine Kategorie von Hand an — herkunft='manuell'.
         */
        post: operations["kategorie_anlegen_api_projekt__projekt_id__kategorien_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/kategorie/{kategorie_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Kategorie Loeschen
         * @description Löscht eine Kategorie. Die Einheiten bleiben, ihre Zuordnung wird offen.
         */
        delete: operations["kategorie_loeschen_api_kategorie__kategorie_id__delete"];
        options?: never;
        head?: never;
        /**
         * Kategorie Aendern
         * @description Ändert eine Kategorie. Sie gilt danach als von Hand geprüft.
         */
        patch: operations["kategorie_aendern_api_kategorie__kategorie_id__patch"];
        trace?: never;
    };
    "/api/projekt/{projekt_id}/dropbox": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Dropbox Stand
         * @description Ob das Projekt mit Dropbox verbunden ist und gegen welchen Ordner.
         *
         *     Der Status kommt aus projekt.dropbox_token. Das alte System prüfte dafür
         *     data/dropbox_tokens.json — eine Datei, die von keiner Zeile geschrieben
         *     wird und mit den tatsächlich benutzten Zugangsdaten nichts zu tun hat.
         */
        get: operations["dropbox_stand_api_projekt__projekt_id__dropbox_get"];
        /**
         * Dropbox Ordner Setzen
         * @description Trägt den Ordner ein, gegen den gelesen wird.
         */
        put: operations["dropbox_ordner_setzen_api_projekt__projekt_id__dropbox_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/dropbox/anmeldung": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Dropbox Anmeldung Beginnen
         * @description Beginnt die Anmeldung. Der begonnene Vorgang steht in der Datenbank.
         *
         *     Damit übersteht er einen Serverneustart zwischen dem Beginn und der
         *     Rückleitung — im alten System lag er in einem Wörterbuch im Arbeitsspeicher.
         */
        post: operations["dropbox_anmeldung_beginnen_api_projekt__projekt_id__dropbox_anmeldung_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/dropbox/ordner": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Dropbox Ordner Auflisten
         * @description Die Ordner im App-Ordner — damit man den Namen nicht wissen muss.
         *
         *     Ein Aufruf: files_list_folder(""). Die App sieht nur ihren eigenen Ordner,
         *     nicht die ganze Dropbox.
         */
        get: operations["dropbox_ordner_auflisten_api_projekt__projekt_id__dropbox_ordner_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/projekt/{projekt_id}/quelle/dropbox": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Quelle Aus Dropbox
         * @description Liest den eingestellten Dropbox-Ordner ein.
         *
         *     Ein zweiter Lauf legt keine zweite Quelle an: bekannte Dateien werden
         *     übersprungen, neue angehängt. Der Riegel steht im Schema —
         *     UNIQUE (quelle_id, quellpfad).
         */
        post: operations["quelle_aus_dropbox_api_projekt__projekt_id__quelle_dropbox_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * AkteurAendernRumpf
         * @description Rumpf von PATCH /api/akteur/{id}. Nur was gesetzt ist, wird geändert.
         */
        AkteurAendernRumpf: {
            /** Normalform */
            normalform?: string | null;
            /**
             * Typ
             * @description null lässt den Typ, wie er ist
             */
            typ?: ("Person" | "Organisation" | "Ort" | "Konzept") | null;
            /** Status */
            status?: ("aktiv" | "abgelehnt") | null;
            /**
             * Aliase
             * @description Ersetzt die Aliasliste vollständig
             */
            aliase?: string[] | null;
        };
        /** AkteurAntwort */
        AkteurAntwort: {
            /** Id */
            id: number;
            /** Projekt Id */
            projekt_id: string;
            /** Normalform */
            normalform: string;
            /** Typ */
            typ: ("Person" | "Organisation" | "Ort" | "Konzept") | null;
            /**
             * Status
             * @enum {string}
             */
            status: "aktiv" | "abgelehnt";
            /**
             * Herkunft
             * @enum {string}
             */
            herkunft: "gliner" | "manuell";
            /** Aliase */
            aliase: string[];
            /** Anzahl Fundstellen */
            anzahl_fundstellen: number;
            /**
             * Aufgeloeste Akteure
             * @description Beim Verschmelzen entfallene Kennungen
             */
            aufgeloeste_akteure?: number[];
        };
        /** AkteurErkennungAntwort */
        AkteurErkennungAntwort: {
            /** Projekt Id */
            projekt_id: string;
            /** Lauf Id */
            lauf_id: number;
            /** Begonnen Am */
            begonnen_am: string;
            /** Beendet Am */
            beendet_am: string;
            /** Status */
            status: string;
            /** Embedding Modell */
            embedding_modell: string;
            /** Gliner Modell */
            gliner_modell: string;
            /** Schwelle */
            schwelle: number;
            /** Anzahl Einheiten */
            anzahl_einheiten: number;
            /** Anzahl Funde */
            anzahl_funde: number;
            /** Anzahl Vor Gruppierung */
            anzahl_vor_gruppierung: number;
            /** Anzahl Neu */
            anzahl_neu: number;
            /** Anzahl Manuell */
            anzahl_manuell: number;
            /** Anzahl Abgelehnt */
            anzahl_abgelehnt: number;
            /** Anzahl Zuordnungen */
            anzahl_zuordnungen: number;
            /** Anzahl Einheiten Mit Akteur */
            anzahl_einheiten_mit_akteur: number;
            /** Anzahl Je Typ */
            anzahl_je_typ: {
                [key: string]: number;
            };
            /** Anzahl Kandidaten Je Grund */
            anzahl_kandidaten_je_grund: {
                [key: string]: number;
            };
            /**
             * Unbekannte Labels
             * @description GLiNER-Label ohne Abbildung; die Funde bleiben ohne Typ
             */
            unbekannte_labels?: {
                [key: string]: number;
            };
            /**
             * Verdraengt Von Manuell
             * @description Funde, die auf einen von Hand gepflegten Namen fielen
             */
            verdraengt_von_manuell?: string[];
        };
        /**
         * AkteureErkennenRumpf
         * @description Rumpf von POST /api/projekt/{id}/akteure/erkennen.
         *
         *     Leer: der Lauf nimmt sich immer alles außer den Handkorrekturen.
         */
        AkteureErkennenRumpf: Record<string, never>;
        /**
         * AnbieterLage
         * @description Was für einen Anbieter eingestellt ist. Nie ein Schlüssel, nie ein Token.
         */
        AnbieterLage: {
            /**
             * Anbieter
             * @description null heißt: nicht gesetzt
             */
            anbieter: string | null;
            /**
             * Bekannt
             * @description steht im Wertevorrat
             */
            bekannt: boolean;
            /**
             * Modell
             * @description Beim Embedding: das Modell für Themen und Zuordnung
             */
            modell: string | null;
            /**
             * Modell Akteure
             * @description Nur beim Embedding: das Modell fürs Zusammenführen von Akteuren. Bei 'local' ein anderes als modell; beim Sprachmodell immer null.
             */
            modell_akteure: string | null;
            /**
             * Schluessel Name
             * @description Welche Variable gebraucht wird; null bei lokalen Anbietern
             */
            schluessel_name: string | null;
            /**
             * Schluessel Vorhanden
             * @description Ob sie gesetzt ist — nicht ihr Wert. null: wird keine gebraucht
             */
            schluessel_vorhanden: boolean | null;
            /** Einsatzbereit */
            einsatzbereit: boolean;
            /**
             * Hinweis
             * @description Was fehlt, in einem Satz
             */
            hinweis?: string | null;
        };
        /** Anker */
        Anker: {
            /** Jahr */
            jahr: number | null;
            /** Herkunft */
            herkunft: string;
            /**
             * Fundstelle
             * @description Was den Anker ausgelöst hat, bei 'manuell' die Begründung
             */
            fundstelle: string;
        };
        /** AnmeldungBeginn */
        AnmeldungBeginn: {
            /**
             * Auth Url
             * @description Dorthin schickt man den Browser
             */
            auth_url: string;
            /** Csrf */
            csrf: string;
            /** Projekt Id */
            projekt_id: string | null;
        };
        /** Ausreisser */
        Ausreisser: {
            /** Projekt Id */
            projekt_id: string;
            /**
             * Unten
             * @description Untere Grenze Q1 − 3·IQR; null, wenn nicht bestimmbar
             */
            unten: number | null;
            /** Oben */
            oben: number | null;
            /** Einheiten */
            einheiten: number[];
        };
        /** Body_quelle_hochladen_api_projekt__projekt_id__quelle_datei_post */
        Body_quelle_hochladen_api_projekt__projekt_id__quelle_datei_post: {
            /**
             * Quellformat
             * @description literaturexzerpt | presseexzerpt
             * @enum {string}
             */
            quellformat: "literaturexzerpt" | "presseexzerpt" | "pressesammlung";
            /**
             * Datei
             * @description Die DOCX-Datei
             */
            datei: string;
        };
        /**
         * DatierenRumpf
         * @description Rumpf von POST /api/projekt/{id}/datieren.
         */
        DatierenRumpf: {
            /**
             * Umfang
             * @description offen = nur nie datierte; alle = auch maschinelle erneut, Handkorrekturen bleiben; auch_manuell = auch diese
             * @default offen
             * @enum {string}
             */
            umfang: "offen" | "alle" | "auch_manuell";
        };
        /** DatierungAntwort */
        DatierungAntwort: {
            /** Projekt Id */
            projekt_id: string;
            /** Quellformat */
            quellformat: string;
            /**
             * Umfang
             * @enum {string}
             */
            umfang: "offen" | "alle" | "auch_manuell";
            /** Lauf Id */
            lauf_id: number;
            /** Begonnen Am */
            begonnen_am: string;
            /** Beendet Am */
            beendet_am: string;
            /** Status */
            status: string;
            /** Anzahl Einheiten */
            anzahl_einheiten: number;
            /** Anzahl Datiert */
            anzahl_datiert: number;
            /** Anzahl Ohne Datum */
            anzahl_ohne_datum: number;
            /** Anzahl Anker */
            anzahl_anker: number;
            /** Anzahl Je Praezision */
            anzahl_je_praezision: {
                [key: string]: number;
            };
            /** Anzahl Je Herkunft */
            anzahl_je_herkunft: {
                [key: string]: number;
            };
            /**
             * Warnungen
             * @description z.B. Handkorrekturen, die auf eine nicht vorhandene Einheit zeigen
             */
            warnungen: string[];
        };
        /**
         * DatierungRumpf
         * @description Rumpf von PATCH /api/einheit/{id}/datierung.
         *
         *     Zwei Felder mit freier Genauigkeit statt einer Vorschrift, wie genau man
         *     sein darf: '2012', '2012-07' oder '2012-07-30'. Die Präzision folgt aus
         *     dem, was dasteht, und wird nicht mitgeschickt.
         */
        DatierungRumpf: {
            /**
             * Datum Von
             * @description '2012' | '2012-07' | '2012-07-30'. null oder leer: undatierbar
             */
            datum_von: string | null;
            /**
             * Datum Bis
             * @description Leer heißt Zeitpunkt statt Zeitraum
             */
            datum_bis?: string | null;
            /**
             * Begruendung
             * @description Warum. Landet in anker.fundstelle — dort, wo bei einem maschinellen Anker die auslösende Zeichenfolge steht
             * @default
             */
            begruendung: string;
        };
        /**
         * DatierungVerteilung
         * @description Woher die Daten kommen. 'interpoliert' heißt geraten.
         */
        DatierungVerteilung: {
            /** Projekt Id */
            projekt_id: string;
            /** Anzahl */
            anzahl: number;
            /** Je Herkunft */
            je_herkunft: {
                [key: string]: number;
            };
            /** Je Praezision */
            je_praezision: {
                [key: string]: number;
            };
            /** Anzahl Interpoliert */
            anzahl_interpoliert: number;
            /** Anzahl Manuell */
            anzahl_manuell: number;
            /** Anzahl Undatiert */
            anzahl_undatiert: number;
            ausreisser: components["schemas"]["Ausreisser"];
            /**
             * Anker
             * @description Die Belege je Einheit, Schlüssel ist die einheit_id als Text
             */
            anker: {
                [key: string]: components["schemas"]["Anker"][];
            };
        };
        /** DatierungZeileAntwort */
        DatierungZeileAntwort: {
            /** Einheit Id */
            einheit_id: number;
            /** Datum */
            datum: string | null;
            /** Jahr Von */
            jahr_von: number | null;
            /** Jahr Bis */
            jahr_bis: number | null;
            /**
             * Praezision
             * @enum {string}
             */
            praezision: "tag" | "monat" | "jahr" | "spanne" | "keine";
            /** Datierung Herkunft */
            datierung_herkunft: string;
            /** Datierung Lauf Id */
            datierung_lauf_id: number | null;
            /** Begruendung */
            begruendung: string;
        };
        /**
         * DropboxOrdnerListe
         * @description Was im App-Ordner liegt — zur Auswahl, statt zum Auswendiglernen.
         */
        DropboxOrdnerListe: {
            /** Projekt Id */
            projekt_id: string;
            /**
             * Ordner
             * @description Pfade wie /Dropbox_test1
             */
            ordner: string[];
        };
        /**
         * DropboxOrdnerRumpf
         * @description Rumpf von PUT /api/projekt/{id}/dropbox.
         */
        DropboxOrdnerRumpf: {
            /**
             * Ordner
             * @description Pfad im App-Ordner, z.B. /Dropbox_test1
             */
            ordner: string;
        };
        /**
         * DropboxStand
         * @description Der Verbindungsstand eines Projekts — aus projekt.dropbox_token.
         */
        DropboxStand: {
            /** Projekt Id */
            projekt_id: string;
            /**
             * Verbunden
             * @description Ob ein refresh_token hinterlegt ist
             */
            verbunden: boolean;
            /** Ordner */
            ordner: string | null;
            /**
             * Anbieter Bereit
             * @description Ob SDK und DROPBOX_APP_KEY/SECRET vorliegen
             */
            anbieter_bereit: boolean;
        };
        /** Einheit */
        Einheit: {
            /** Id */
            id: number;
            /** Quelle Id */
            quelle_id: string;
            /** Position */
            position: number;
            /** Typ */
            typ: string;
            /** Text */
            text: string;
            /** Publikation */
            publikation?: string | null;
            /** Chronologie Gruppe */
            chronologie_gruppe?: string | null;
            /** Publikationsdatum */
            publikationsdatum?: string | null;
            /** Quellpfad */
            quellpfad?: string | null;
            /** Url */
            url?: string | null;
            /** Autor */
            autor?: string | null;
            /** Kurzfassung */
            kurzfassung?: string | null;
            /** Seite */
            seite?: number | null;
            /** Ebene */
            ebene?: number | null;
            /** Ist Zitat */
            ist_zitat?: boolean | null;
            /** Datum */
            datum?: string | null;
            /** Jahr Von */
            jahr_von?: number | null;
            /** Jahr Bis */
            jahr_bis?: number | null;
            /** Praezision */
            praezision?: string | null;
            /** Datierung Herkunft */
            datierung_herkunft?: string | null;
            /** Datierung Lauf Id */
            datierung_lauf_id?: number | null;
            /** Kategorie Id */
            kategorie_id?: number | null;
            /** Konfidenz */
            konfidenz?: string | null;
            /**
             * Kategorie Herkunft
             * @description automatisch | manuell. NULL = nie zugeordnet; manuell ist gegen jeden Neulauf geschützt
             */
            kategorie_herkunft?: string | null;
        };
        /** EinheitenListe */
        EinheitenListe: {
            /** Projekt Id */
            projekt_id: string;
            /** Anzahl */
            anzahl: number;
            /**
             * Typ Filter
             * @description Der angewandte Filter, oder null für ungefiltert
             */
            typ_filter?: ("content" | "heading" | "bibliography" | "meta") | null;
            /** Einheiten */
            einheiten: components["schemas"]["Einheit"][];
        };
        /** ExportAntwort */
        ExportAntwort: {
            /** Projekt Id */
            projekt_id: string;
            /** Ziel */
            ziel: string;
            /** Lauf Id */
            lauf_id: number;
            /** Begonnen Am */
            begonnen_am: string;
            /** Beendet Am */
            beendet_am: string;
            /** Status */
            status: string;
            /** Dateien */
            dateien: string[];
            /** Anzahl Einheiten */
            anzahl_einheiten: number;
            /** Anzahl Mit Datum */
            anzahl_mit_datum: number;
            /**
             * Anzahl Ohne Datum
             * @description Fehlen auf der Zeitachse — die Zahl steht hier, nicht nur im Bild
             */
            anzahl_ohne_datum: number;
            /** Anzahl Ohne Kategorie */
            anzahl_ohne_kategorie: number;
            /** Anzahl Mit Akteur */
            anzahl_mit_akteur: number;
            /** Anzahl Akteure */
            anzahl_akteure: number;
            /** Anzahl Knoten */
            anzahl_knoten: number;
            /** Anzahl Kanten */
            anzahl_kanten: number;
            /** Anzahl Je Kategorie */
            anzahl_je_kategorie: {
                [key: string]: number;
            };
            /**
             * Jahr Min
             * @description MIN(einheit.jahr_von), abgeleitet
             */
            jahr_min: number | null;
            /**
             * Jahr Max
             * @description MAX(einheit.jahr_bis), abgeleitet
             */
            jahr_max: number | null;
            /** Zusammenfassungen */
            zusammenfassungen: number;
        };
        /**
         * ExportierenRumpf
         * @description Rumpf von POST /api/projekt/{id}/exportieren.
         */
        ExportierenRumpf: {
            /**
             * Zusammenfassungen
             * @description entities_summary.json aus akteur.zusammenfassung schreiben. Vorgabe aus — gilt auf jedem Weg gleich
             * @default false
             */
            zusammenfassungen: boolean;
        };
        /**
         * Fehler
         * @description Die eine Fehlergestalt.
         */
        Fehler: {
            /**
             * Code
             * @description Maschinenlesbare Kennung, z.B. projekt_nicht_gefunden
             */
            code: string;
            /**
             * Meldung
             * @description Erklärung für Menschen, deutsch
             */
            meldung: string;
            /**
             * Status
             * @description HTTP-Status, wiederholt für Clients ohne Zugriff darauf
             */
            status: number;
        };
        /** FehlerAntwort */
        FehlerAntwort: {
            fehler: components["schemas"]["Fehler"];
        };
        /** IngestAntwort */
        IngestAntwort: {
            /** Projekt Id */
            projekt_id: string;
            /** Quelle Id */
            quelle_id: string;
            /**
             * Quellformat
             * @enum {string}
             */
            quellformat: "literaturexzerpt" | "presseexzerpt" | "pressesammlung";
            /** Pfad */
            pfad: string;
            /** Lauf Id */
            lauf_id: number;
            /** Begonnen Am */
            begonnen_am: string;
            /** Beendet Am */
            beendet_am: string;
            /** Status */
            status: string;
            /**
             * Anzahl Einheiten
             * @description Stand der Quelle nach dem Lauf
             */
            anzahl_einheiten: number;
            /** Anzahl Je Typ */
            anzahl_je_typ: {
                [key: string]: number;
            };
            /**
             * Fortgesetzt
             * @description Ob eine vorhandene Quelle fortgeführt wurde
             */
            fortgesetzt: boolean;
            /** Anzahl Neu */
            anzahl_neu: number;
            /**
             * Anzahl Uebersprungen
             * @description Dateien, die schon in der Quelle standen
             */
            anzahl_uebersprungen: number;
            /**
             * Geaenderte Dateien
             * @description Bekannte Dateien mit geändertem Inhalt — gemeldet, nicht angefasst
             */
            geaenderte_dateien: string[];
            /** Hinweise */
            hinweise: string[];
        };
        /** Kandidat */
        Kandidat: {
            /** Id */
            id: number;
            /** Akteur A Id */
            akteur_a_id: number;
            /** Akteur A */
            akteur_a: string;
            /** Akteur B Id */
            akteur_b_id: number;
            /** Akteur B */
            akteur_b: string;
            /**
             * Grund
             * @enum {string}
             */
            grund: "alias" | "schreibweise" | "aehnlichkeit";
            /**
             * Mass
             * @description Kosinusähnlichkeit bzw. Editierabstand; null bei 'alias'
             */
            mass: number | null;
            /** Berechnet Am */
            berechnet_am: string;
        };
        /** KandidatenListe */
        KandidatenListe: {
            /** Projekt Id */
            projekt_id: string;
            /** Anzahl */
            anzahl: number;
            /** Kandidaten */
            kandidaten: components["schemas"]["Kandidat"][];
        };
        /**
         * KategorieEintrag
         * @description Eine Zeile im Editor. Ohne id wird angelegt, mit id geändert.
         *
         *     Ohne Vorgabewerte, damit die erzeugten TypeScript-Typen die Felder als
         *     vorhanden führen: der Editor schickt immer die ganze Zeile.
         */
        KategorieEintrag: {
            /** Id */
            id: number | null;
            /** Name */
            name: string;
            /** Beschreibung */
            beschreibung: string;
            /** Schlagworte */
            schlagworte: string[];
        };
        /**
         * KategorieRumpf
         * @description Rumpf zum Anlegen und Ändern. Nur was gesetzt ist, wird geändert.
         */
        KategorieRumpf: {
            /** Name */
            name?: string | null;
            /** Beschreibung */
            beschreibung?: string | null;
            /** Schlagworte */
            schlagworte?: string[] | null;
        };
        /** KategorieZeile */
        KategorieZeile: {
            /** Id */
            id: number;
            /** Projekt Id */
            projekt_id: string;
            /** Name */
            name: string;
            /** Beschreibung */
            beschreibung: string;
            /** Schlagworte */
            schlagworte: string[];
            /**
             * Herkunft
             * @description vorschlag = aus einem Lauf, manuell = von Hand angefasst
             * @enum {string}
             */
            herkunft: "vorschlag" | "manuell";
            /**
             * Anzahl Einheiten
             * @description Wie viele Einheiten darauf zeigen
             */
            anzahl_einheiten: number;
        };
        /**
         * KategorienGespeichert
         * @description Antwort auf PUT /api/projekt/{id}/kategorien.
         *
         *     Kein LaufBegonnen, weil es nicht immer einen Lauf gibt: wer alle Kategorien
         *     entfernt, hat nichts, wogegen zugeordnet werden könnte. Dann ist lauf_id
         *     null und das Speichern ist fertig — vorher scheiterte an dieser Stelle ein
         *     Lauf mit 'keine_taxonomie', obwohl das Löschen gelungen war.
         */
        KategorienGespeichert: {
            /** Projekt Id */
            projekt_id: string;
            /**
             * Anzahl
             * @description Kategorien nach dem Speichern
             */
            anzahl: number;
            /** Angelegt */
            angelegt: number;
            /** Geaendert */
            geaendert: number;
            /** Geloescht */
            geloescht: number;
            /**
             * Lauf Id
             * @description Der Zuordnungslauf; null, wenn es nichts zuzuordnen gibt
             */
            lauf_id: number | null;
        };
        /** KategorienListe */
        KategorienListe: {
            /** Projekt Id */
            projekt_id: string;
            /** Anzahl */
            anzahl: number;
            /** Kategorien */
            kategorien: components["schemas"]["KategorieZeile"][];
            /** Anzahl Ohne Kategorie */
            anzahl_ohne_kategorie: number;
            /**
             * Anzahl Manuell Zugeordnet
             * @description Handkorrekturen — vor jedem Neulauf sicher
             */
            anzahl_manuell_zugeordnet: number;
            /**
             * Einheiten Ohne Vektor
             * @description Wie viele Einheiten beim nächsten Zuordnen erst embeddet werden müssen. 0 heißt: das Speichern ist in etwa einer Sekunde durch. null, wenn kein Embedding-Anbieter steht.
             */
            einheiten_ohne_vektor: number | null;
        };
        /**
         * KategorienSpeichernRumpf
         * @description Rumpf von PUT /api/projekt/{id}/kategorien.
         *
         *     Die ganze Liste auf einmal: was fehlt, wird gelöscht. Danach wird neu
         *     zugeordnet — das ist der Moment, in dem Beschreibungen und Zuordnung wieder
         *     zusammenpassen.
         */
        KategorienSpeichernRumpf: {
            /** Kategorien */
            kategorien: components["schemas"]["KategorieEintrag"][];
        };
        /**
         * Kennzahlen
         * @description Was ein Projekt in der Datenbank stehen hat — alles gerechnet.
         */
        Kennzahlen: {
            /** Projekt Id */
            projekt_id: string;
            /** Titel */
            titel: string;
            /** Quellformate */
            quellformate: ("literaturexzerpt" | "presseexzerpt" | "pressesammlung")[];
            /** Anzahl Quellen */
            anzahl_quellen: number;
            /** Anzahl Einheiten */
            anzahl_einheiten: number;
            /** Anzahl Je Typ */
            anzahl_je_typ: {
                [key: string]: number;
            };
            /** Anzahl Datiert */
            anzahl_datiert: number;
            /** Anzahl Ohne Datum */
            anzahl_ohne_datum: number;
            /** Anzahl Kategorien */
            anzahl_kategorien: number;
            /** Anzahl Klassifiziert */
            anzahl_klassifiziert: number;
            /** Anzahl Akteure */
            anzahl_akteure: number;
            /** Anzahl Fundstellen */
            anzahl_fundstellen: number;
            /** Jahr Von */
            jahr_von: number | null;
            /** Jahr Bis */
            jahr_bis: number | null;
            /** Hat Export */
            hat_export: boolean;
            /**
             * Laeufe
             * @description Die letzten Läufe, neueste zuerst
             */
            laeufe: components["schemas"]["Lauf"][];
        };
        /**
         * KlassifizierenRumpf
         * @description Rumpf von POST /api/projekt/{id}/klassifizieren.
         *
         *     Kein Umfang: zugeordnet wird immer alles, und Handkorrekturen bleiben
         *     unangetastet. Das ist eine Regel, keine Einstellung — sie zur Wahl zu
         *     stellen hieße, das Überschreiben von Handarbeit als gleichwertige
         *     Möglichkeit anzubieten.
         */
        KlassifizierenRumpf: {
            /**
             * Verfahren
             * @description bge = lokal, llm = API
             * @default bge
             * @enum {string}
             */
            verfahren: "bge" | "llm";
        };
        /** KonfigurationAntwort */
        KonfigurationAntwort: {
            /** Env Datei */
            env_datei: string | null;
            embedding: components["schemas"]["AnbieterLage"];
            llm: components["schemas"]["AnbieterLage"];
            /**
             * Schwelle Akteure
             * @description Ab hier werden Akteure zusammengeführt; hängt am Modell
             */
            schwelle_akteure: number | null;
            /**
             * Band Akteure
             * @description Der Streifen darunter, aus dem Vorschläge kommen
             */
            band_akteure: [
                number,
                number
            ] | null;
            /** Schwellen Kategorien */
            schwellen_kategorien: {
                [key: string]: number;
            };
            /**
             * Ollama Frist Sekunden
             * @description Frist je Modellaufruf; null, wenn Ollama nicht aktiv ist
             */
            ollama_frist_sekunden: number | null;
        };
        /** Lauf */
        Lauf: {
            /** Id */
            id: number;
            /** Schritt */
            schritt: string;
            /** Status */
            status: string;
            /** Begonnen Am */
            begonnen_am: string;
            /** Beendet Am */
            beendet_am: string | null;
        };
        /**
         * LaufBegonnen
         * @description Antwort auf das Anstoßen eines langen Schritts.
         */
        LaufBegonnen: {
            /** Lauf Id */
            lauf_id: number;
            /** Projekt Id */
            projekt_id: string;
            /** Schritt */
            schritt: string;
            /**
             * Status
             * @description immer 'laeuft' — der Stand kommt aus GET /api/lauf/{id}
             */
            status: string;
        };
        /**
         * LaufStand
         * @description Der Stand eines Schritts — abgefragt, nicht gestreamt.
         *
         *     Der Fortschritt steht in der lauf-Zeile: reißt die Verbindung, ist er
         *     trotzdem da, und ein neu geladener Reiter sieht denselben Lauf.
         */
        LaufStand: {
            /** Id */
            id: number;
            /** Projekt Id */
            projekt_id: string;
            /** Schritt */
            schritt: string;
            /**
             * Status
             * @description laeuft | erfolg | fehler
             */
            status: string;
            /** Begonnen Am */
            begonnen_am: string;
            /** Beendet Am */
            beendet_am: string | null;
            /**
             * Parameter
             * @description Was der Schritt bisher gemeldet hat; am Ende sein Ergebnis
             */
            parameter: {
                [key: string]: unknown;
            };
            /** Fehler */
            fehler: string | null;
        };
        /** Projekt */
        Projekt: {
            /** Id */
            id: string;
            /** Titel */
            titel: string;
            /** Eigentuemer Id */
            eigentuemer_id: number;
            /** Angelegt Am */
            angelegt_am: string;
            /** Oeffentlich */
            oeffentlich: boolean;
            /** Dropbox Ordner */
            dropbox_ordner?: string | null;
        };
        /**
         * ProjektAnlegenRumpf
         * @description Rumpf von POST /api/projekte.
         */
        ProjektAnlegenRumpf: {
            /**
             * Titel
             * @description Anzeigename, z.B. 'Damaskus'
             */
            titel: string;
            /**
             * Id
             * @description Kennung; ohne Angabe aus dem Titel abgeleitet
             */
            id?: string | null;
        };
        /** ProjektListe */
        ProjektListe: {
            /** Anzahl */
            anzahl: number;
            /** Projekte */
            projekte: components["schemas"]["ProjektZeile"][];
        };
        /**
         * ProjektZeile
         * @description Ein Projekt mit den Zahlen, die die Übersicht zeigt.
         *
         *     Alle Werte sind gerechnet, keiner steht in einer Konfigurationsdatei:
         *     anzahl_einheiten ist COUNT(*), der Zeitraum MIN/MAX über die Einheiten.
         */
        ProjektZeile: {
            /** Id */
            id: string;
            /** Titel */
            titel: string;
            /** Eigentuemer Id */
            eigentuemer_id: number;
            /** Angelegt Am */
            angelegt_am: string;
            /** Oeffentlich */
            oeffentlich: boolean;
            /** Dropbox Ordner */
            dropbox_ordner?: string | null;
            /**
             * Quellformate
             * @description Je Quelle eines; meist genau eines. Leer, solange keine Quelle da ist
             */
            quellformate: ("literaturexzerpt" | "presseexzerpt" | "pressesammlung")[];
            /** Anzahl Quellen */
            anzahl_quellen: number;
            /**
             * Anzahl Einheiten
             * @description content-Einheiten, COUNT(*)
             */
            anzahl_einheiten: number;
            /**
             * Jahr Von
             * @description MIN(einheit.jahr_von), abgeleitet
             */
            jahr_von: number | null;
            /**
             * Jahr Bis
             * @description MAX(einheit.jahr_bis), abgeleitet
             */
            jahr_bis: number | null;
            /**
             * Hat Export
             * @description Ob exploration/data.json vorliegt — nur dann führt der Viz-Link irgendwohin
             */
            hat_export: boolean;
        };
        /**
         * QuelleAnlegen
         * @description Rumpf von POST /api/projekt/{id}/quelle.
         */
        QuelleAnlegen: {
            /**
             * Pfad
             * @description Pfad unterhalb von data/raw/, z.B. 'Notizen.docx'
             */
            pfad: string;
            /**
             * Quellformat
             * @enum {string}
             */
            quellformat: "literaturexzerpt" | "presseexzerpt" | "pressesammlung";
        };
        /**
         * TaxonomieVorschlagRumpf
         * @description Rumpf von POST /api/projekt/{id}/taxonomie/vorschlagen.
         */
        TaxonomieVorschlagRumpf: {
            /**
             * Warm Start
             * @description false = neu vorschlagen, ohne Ausgangspunkt; true = die vorhandenen Kategorien verfeinern
             * @default false
             */
            warm_start: boolean;
            /**
             * N Clusters
             * @description Anzahl Kategorien; nur ohne warm_start erlaubt (Vorgabe 7)
             */
            n_clusters?: number | null;
        };
        /** TextAntwort */
        TextAntwort: {
            /** Einheit Id */
            einheit_id: number;
            /** Projekt Id */
            projekt_id: string;
            /** Text */
            text: string;
            /** Geaendert */
            geaendert: boolean;
            /**
             * Fundstellen Geloescht
             * @description Akteursfundstellen dieser Einheit — gelöscht, nicht umgerechnet. Veraltete Zeichenpositionen markieren sonst still die falschen Wörter
             */
            fundstellen_geloescht: number;
            /**
             * Datierung Neu
             * @description Einheiten des Projekts, deren Datierung sich dadurch geändert hat — die Nachbarn hängen über die Interpolation mit dran
             */
            datierung_neu: number;
        };
        /**
         * TextRumpf
         * @description Rumpf von PATCH /api/einheit/{id}/text.
         */
        TextRumpf: {
            /** Text */
            text: string;
        };
        /**
         * VerschmelzenRumpf
         * @description Rumpf von POST /api/akteure/verschmelzen.
         */
        VerschmelzenRumpf: {
            /**
             * Ids
             * @description Mindestens zwei Akteure
             */
            ids: number[];
            /**
             * Behalten Id
             * @description Dessen Normalform bleibt stehen
             */
            behalten_id: number;
        };
        /** ZuordnungAntwort */
        ZuordnungAntwort: {
            /** Einheit Id */
            einheit_id: number;
            /** Kategorie Id */
            kategorie_id: number | null;
            /** Konfidenz */
            konfidenz: string | null;
            /** Kategorie Herkunft */
            kategorie_herkunft: string;
            /** Kategorie Lauf Id */
            kategorie_lauf_id: number | null;
        };
        /**
         * ZuordnungRumpf
         * @description Rumpf von PATCH /api/einheit/{id}/kategorie.
         */
        ZuordnungRumpf: {
            /**
             * Kategorie Id
             * @description Kennung der Kategorie, oder null für 'keine Kategorie'
             */
            kategorie_id: number | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    konfiguration_api_konfiguration_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KonfigurationAntwort"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    projekte_api_projekte_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjektListe"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    projekt_anlegen_api_projekte_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProjektAnlegenRumpf"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjektZeile"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    projekt_kennzahlen_api_projekt__projekt_id__kennzahlen_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Kennzahlen"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    projekt_api_projekt__projekt_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Projekt"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    projekt_loeschen_api_projekt__projekt_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    einheiten_api_projekt__projekt_id__einheiten_get: {
        parameters: {
            query?: {
                /** @description Filter auf einheit.typ */
                typ?: ("content" | "heading" | "bibliography" | "meta") | null;
            };
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EinheitenListe"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    quelle_anlegen_api_projekt__projekt_id__quelle_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QuelleAnlegen"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IngestAntwort"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    projekt_klassifizieren_api_projekt__projekt_id__klassifizieren_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["KlassifizierenRumpf"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LaufBegonnen"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    kategorie_von_hand_setzen_api_einheit__einheit_id__kategorie_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                einheit_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ZuordnungRumpf"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ZuordnungAntwort"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    lauf_stand_api_lauf__lauf_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                lauf_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LaufStand"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    taxonomie_vorschlagen_api_projekt__projekt_id__taxonomie_vorschlagen_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TaxonomieVorschlagRumpf"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LaufBegonnen"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    projekt_datieren_api_projekt__projekt_id__datieren_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DatierenRumpf"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DatierungAntwort"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    datierung_von_hand_setzen_api_einheit__einheit_id__datierung_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                einheit_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DatierungRumpf"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DatierungZeileAntwort"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    einheit_text_setzen_api_einheit__einheit_id__text_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                einheit_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TextRumpf"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TextAntwort"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    datierung_verteilung_api_projekt__projekt_id__datierung_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DatierungVerteilung"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    akteure_erkennen_api_projekt__projekt_id__akteure_erkennen_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["AkteureErkennenRumpf"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AkteurErkennungAntwort"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    akteur_von_hand_aendern_api_akteur__akteur_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                akteur_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AkteurAendernRumpf"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AkteurAntwort"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    akteure_zusammenlegen_api_akteure_verschmelzen_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VerschmelzenRumpf"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AkteurAntwort"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    akteure_duplikatskandidaten_api_projekt__projekt_id__akteure_duplikatskandidaten_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KandidatenListe"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    projekt_exportieren_api_projekt__projekt_id__exportieren_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ExportierenRumpf"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExportAntwort"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    quelle_hochladen_api_projekt__projekt_id__quelle_datei_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_quelle_hochladen_api_projekt__projekt_id__quelle_datei_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IngestAntwort"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    kategorien_liste_api_projekt__projekt_id__kategorien_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KategorienListe"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    kategorien_speichern_api_projekt__projekt_id__kategorien_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["KategorienSpeichernRumpf"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KategorienGespeichert"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    kategorie_anlegen_api_projekt__projekt_id__kategorien_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["KategorieRumpf"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KategorieZeile"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    kategorie_loeschen_api_kategorie__kategorie_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                kategorie_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    kategorie_aendern_api_kategorie__kategorie_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                kategorie_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["KategorieRumpf"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KategorieZeile"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    dropbox_stand_api_projekt__projekt_id__dropbox_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DropboxStand"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    dropbox_ordner_setzen_api_projekt__projekt_id__dropbox_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DropboxOrdnerRumpf"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DropboxStand"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    dropbox_anmeldung_beginnen_api_projekt__projekt_id__dropbox_anmeldung_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnmeldungBeginn"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    dropbox_ordner_auflisten_api_projekt__projekt_id__dropbox_ordner_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DropboxOrdnerListe"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
    quelle_aus_dropbox_api_projekt__projekt_id__quelle_dropbox_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                projekt_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IngestAntwort"];
                };
            };
            /** @description Nicht gefunden */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Steht dem gerade etwas entgegen */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ungültiger Parameter */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Serverfehler */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Ein Dienst dahinter antwortet nicht */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
            /** @description Anbieter nicht verfügbar */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FehlerAntwort"];
                };
            };
        };
    };
}
