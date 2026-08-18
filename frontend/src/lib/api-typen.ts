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
         * @description Alle Projekte, nach Anlagedatum.
         */
        get: operations["projekte_api_projekte_get"];
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
        delete?: never;
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
         * @description Ordnet den offenen Einheiten eines Projekts Kategorien zu.
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
         * @description Schlägt eine Taxonomie vor — von null oder aus den vorhandenen Kategorien.
         *
         *     warm_start=false: neu vorschlagen, n_clusters wählbar.
         *     warm_start=true : verfeinern, n_clusters ist die Anzahl der vorhandenen.
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
         *     jahr_von=null heißt undatierbar. Die Korrektur wird eine anker-Zeile mit
         *     herkunft='manuell' und überlebt jeden Neulauf außer 'auch_manuell'.
         */
        patch: operations["datierung_von_hand_setzen_api_einheit__einheit_id__datierung_patch"];
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
            /** Modell */
            modell: string | null;
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
            warnungen?: string[];
        };
        /**
         * DatierungRumpf
         * @description Rumpf von PATCH /api/einheit/{id}/datierung.
         */
        DatierungRumpf: {
            /**
             * Jahr Von
             * @description null bedeutet: undatierbar
             */
            jahr_von: number | null;
            /**
             * Jahr Bis
             * @description nur bei einer Spanne
             */
            jahr_bis?: number | null;
            /**
             * Datum
             * @description genauer als das Jahr, ISO
             */
            datum?: string | null;
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
            /** Anzahl Perioden */
            anzahl_perioden: number;
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
            /** Anzahl Einheiten */
            anzahl_einheiten: number;
            /** Anzahl Je Typ */
            anzahl_je_typ: {
                [key: string]: number;
            };
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
        /** KlassifikationAntwort */
        KlassifikationAntwort: {
            /** Projekt Id */
            projekt_id: string;
            /**
             * Verfahren
             * @enum {string}
             */
            verfahren: "bge" | "llm";
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
            /** Anzahl Ohne Kategorie */
            anzahl_ohne_kategorie: number;
            /** Anzahl Je Konfidenz */
            anzahl_je_konfidenz: {
                [key: string]: number;
            };
            /** Anzahl Je Kategorie */
            anzahl_je_kategorie: {
                [key: string]: number;
            };
        };
        /**
         * KlassifizierenRumpf
         * @description Rumpf von POST /api/projekt/{id}/klassifizieren.
         */
        KlassifizierenRumpf: {
            /**
             * Verfahren
             * @description bge = lokal, llm = API
             * @default bge
             * @enum {string}
             */
            verfahren: "bge" | "llm";
            /**
             * Umfang
             * @description offen = nur nie klassifizierte; alle = auch maschinelle erneut, Handkorrekturen bleiben; auch_manuell = auch Handkorrekturen überschreiben
             * @default offen
             * @enum {string}
             */
            umfang: "offen" | "alle" | "auch_manuell";
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
        /** ProjektListe */
        ProjektListe: {
            /** Anzahl */
            anzahl: number;
            /** Projekte */
            projekte: components["schemas"]["Projekt"][];
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
        /** TaxonomieAntwort */
        TaxonomieAntwort: {
            /** Projekt Id */
            projekt_id: string;
            /** Warm Start */
            warm_start: boolean;
            /** Lauf Id */
            lauf_id: number;
            /** Begonnen Am */
            begonnen_am: string;
            /** Beendet Am */
            beendet_am: string;
            /** Status */
            status: string;
            /** N Clusters */
            n_clusters: number;
            /** Kategorien */
            kategorien: {
                [key: string]: unknown;
            }[];
            /** Llm Runden */
            llm_runden: number;
            /** Fruehzeitig Beendet */
            fruehzeitig_beendet: boolean;
            /** Eingefroren */
            eingefroren: number[];
            /** In Tokens */
            in_tokens: number;
            /** Out Tokens */
            out_tokens: number;
            /** Kosten Usd */
            kosten_usd: number;
            /** Embedding Modell */
            embedding_modell: string;
            /** Llm Modell */
            llm_modell: string;
            /** Trajektorie */
            trajektorie: {
                [key: string]: unknown;
            }[];
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
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KlassifikationAntwort"];
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
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaxonomieAntwort"];
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
