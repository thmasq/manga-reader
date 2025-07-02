-- Create custom types
CREATE TYPE STATUS AS ENUM ('ongoing', 'completed', 'hiatus', 'cancelled', 'unknown');

-- Main entity tables
CREATE TABLE MANGA (
    manga_id SERIAL PRIMARY KEY,
    name_original TEXT,
    name_romanized VARCHAR(500),
    name_english VARCHAR(500),
    manga_status STATUS DEFAULT 'unknown',
    started_publishing DATE,
    ended_publishing DATE,
    cover_path VARCHAR(4096),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT check_publishing_dates 
        CHECK (ended_publishing IS NULL OR ended_publishing >= started_publishing)
);

CREATE TABLE CHAPTER (
    chapter_id SERIAL PRIMARY KEY,
    chapter_num DECIMAL(10,2) NOT NULL,
    page_count INTEGER,
    manga_id INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(manga_id, chapter_num)
);

CREATE TABLE AUTHOR (
    author_id SERIAL PRIMARY KEY,
    name_romanized VARCHAR(200) NOT NULL
);

CREATE TABLE PAGES (
    page_id SERIAL PRIMARY KEY,
    page_num INTEGER NOT NULL,
    page_path VARCHAR(4096),
    chapter_id INTEGER NOT NULL,
    language_id VARCHAR(10) NOT NULL,
    
    UNIQUE(chapter_id, page_num, language_id)
);

CREATE TABLE tag (
    tag_id SERIAL PRIMARY KEY,
    tag_name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE LANGUAGE (
    language_id VARCHAR(10) PRIMARY KEY,
    language_name_en VARCHAR(100) NOT NULL
);

-- Junction tables for many-to-many relationships
CREATE TABLE writes (
    author_id INTEGER NOT NULL,
    manga_id INTEGER NOT NULL,
    role VARCHAR(50) DEFAULT 'author',
    
    PRIMARY KEY (author_id, manga_id, role)
);

CREATE TABLE has (
    tag_id INTEGER NOT NULL,
    manga_id INTEGER NOT NULL,
    
    PRIMARY KEY (tag_id, manga_id)
);

CREATE TABLE supports (
    language_id VARCHAR(10) NOT NULL,
    manga_id INTEGER NOT NULL,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    PRIMARY KEY (language_id, manga_id)
);

CREATE TABLE translated_to (
    language_id VARCHAR(10) NOT NULL,
    chapter_id INTEGER NOT NULL,
    translation_date DATE,
    translator_notes TEXT,
    is_complete BOOLEAN DEFAULT FALSE,
    
    PRIMARY KEY (language_id, chapter_id)
);

-- Foreign key constraints
ALTER TABLE CHAPTER ADD CONSTRAINT FK_CHAPTER_2
    FOREIGN KEY (manga_id)
    REFERENCES MANGA (manga_id)
    ON DELETE CASCADE;

ALTER TABLE PAGES ADD CONSTRAINT FK_PAGES_2
    FOREIGN KEY (chapter_id)
    REFERENCES CHAPTER (chapter_id)
    ON DELETE CASCADE;

ALTER TABLE PAGES ADD CONSTRAINT FK_PAGES_3
    FOREIGN KEY (language_id)
    REFERENCES LANGUAGE (language_id)
    ON DELETE CASCADE;

ALTER TABLE writes ADD CONSTRAINT FK_writes_1
    FOREIGN KEY (author_id)
    REFERENCES AUTHOR (author_id)
    ON DELETE CASCADE;

ALTER TABLE writes ADD CONSTRAINT FK_writes_2
    FOREIGN KEY (manga_id)
    REFERENCES MANGA (manga_id)
    ON DELETE CASCADE;

ALTER TABLE has ADD CONSTRAINT FK_has_1
    FOREIGN KEY (tag_id)
    REFERENCES tag (tag_id)
    ON DELETE CASCADE;

ALTER TABLE has ADD CONSTRAINT FK_has_2
    FOREIGN KEY (manga_id)
    REFERENCES MANGA (manga_id)
    ON DELETE CASCADE;

ALTER TABLE supports ADD CONSTRAINT FK_supports_1
    FOREIGN KEY (language_id)
    REFERENCES LANGUAGE (language_id)
    ON DELETE CASCADE;

ALTER TABLE supports ADD CONSTRAINT FK_supports_2
    FOREIGN KEY (manga_id)
    REFERENCES MANGA (manga_id)
    ON DELETE CASCADE;

ALTER TABLE translated_to ADD CONSTRAINT FK_translated_to_1
    FOREIGN KEY (language_id)
    REFERENCES LANGUAGE (language_id)
    ON DELETE CASCADE;

ALTER TABLE translated_to ADD CONSTRAINT FK_translated_to_2
    FOREIGN KEY (chapter_id)
    REFERENCES CHAPTER (chapter_id)
    ON DELETE CASCADE;

-- Trigger function to ensure chapters can only be translated to languages the manga supports
CREATE OR REPLACE FUNCTION check_translation_language_support()
RETURNS TRIGGER AS $$
BEGIN
    -- Check if the manga supports the language being used for translation
    IF NOT EXISTS (
        SELECT 1 FROM supports s
        JOIN chapter c ON NEW.chapter_id = c.chapter_id
        WHERE s.language_id = NEW.language_id 
        AND s.manga_id = c.manga_id
    ) THEN
        RAISE EXCEPTION 'Language % is not supported for this manga', NEW.language_id;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply the trigger to translated_to table
CREATE TRIGGER trigger_check_translation_language
    BEFORE INSERT OR UPDATE ON translated_to
    FOR EACH ROW
    EXECUTE FUNCTION check_translation_language_support();

-- Constraint to ensure pages can only exist for translated chapters
ALTER TABLE PAGES ADD CONSTRAINT FK_pages_translation
    FOREIGN KEY (language_id, chapter_id)
    REFERENCES translated_to (language_id, chapter_id)
    ON DELETE CASCADE;

-- Indexes for performance
CREATE INDEX idx_manga_status ON MANGA(manga_status);
CREATE INDEX idx_manga_dates ON MANGA(started_publishing, ended_publishing);
CREATE INDEX idx_chapter_manga ON CHAPTER(manga_id);
CREATE INDEX idx_pages_chapter ON PAGES(chapter_id);
CREATE INDEX idx_pages_language ON PAGES(language_id);
CREATE INDEX idx_pages_chapter_lang ON PAGES(chapter_id, language_id);
CREATE INDEX idx_writes_author ON writes(author_id);
CREATE INDEX idx_writes_manga ON writes(manga_id);
CREATE INDEX idx_has_tag ON has(tag_id);
CREATE INDEX idx_has_manga ON has(manga_id);
CREATE INDEX idx_supports_manga ON supports(manga_id);
CREATE INDEX idx_translated_chapter ON translated_to(chapter_id);

-- Trigger for updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_manga_updated_at 
    BEFORE UPDATE ON MANGA 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Insert common languages
INSERT INTO LANGUAGE (language_id, language_name_en) VALUES 
    ('en', 'English'),
    ('ja', 'Japanese'),
    ('es', 'Spanish'),
    ('fr', 'French'),
    ('de', 'German'),
    ('pt', 'Portuguese'),
    ('ko', 'Korean'),
    ('zh-CN', 'Chinese (Simplified)'),
    ('zh-TW', 'Chinese (Traditional)'),
    ('it', 'Italian'),
    ('ru', 'Russian'),
    ('ar', 'Arabic');
