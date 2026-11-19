-- =============================================================
-- Bookstore Management System - Database Schema (MySQL 8.x)
-- Run this whole file in MySQL Workbench (lightning-bolt button)
-- It drops and re-creates the database with sample data.
-- =============================================================

DROP DATABASE IF EXISTS bookstore;
CREATE DATABASE bookstore;
USE bookstore;

-- ---------- AUTHORS ----------
CREATE TABLE authors (
    author_id   INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    country     VARCHAR(60)
);

-- ---------- BOOKS ----------
-- Each book has exactly one author (many books -> one author).
CREATE TABLE books (
    book_id     INT AUTO_INCREMENT PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    author_id   INT NOT NULL,
    isbn        VARCHAR(20) NOT NULL UNIQUE,
    genre       VARCHAR(50),
    price       DECIMAL(8,2) NOT NULL CHECK (price >= 0),
    stock       INT NOT NULL DEFAULT 0 CHECK (stock >= 0),
    CONSTRAINT fk_books_author FOREIGN KEY (author_id)
        REFERENCES authors(author_id) ON DELETE RESTRICT
);

-- ---------- CUSTOMERS ----------
CREATE TABLE customers (
    customer_id INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    email       VARCHAR(120) NOT NULL UNIQUE,
    phone       VARCHAR(20)
);

-- ---------- ORDERS ----------
CREATE TABLE orders (
    order_id    INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    order_date  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status      ENUM('Pending','Shipped','Delivered','Cancelled') NOT NULL DEFAULT 'Pending',
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id)
        REFERENCES customers(customer_id) ON DELETE CASCADE
);

-- ---------- ORDER_ITEMS (junction table: orders <-> books, M:N) ----------
CREATE TABLE order_items (
    order_id    INT NOT NULL,
    book_id     INT NOT NULL,
    quantity    INT NOT NULL CHECK (quantity > 0),
    unit_price  DECIMAL(8,2) NOT NULL,          -- price at time of purchase
    PRIMARY KEY (order_id, book_id),
    CONSTRAINT fk_items_order FOREIGN KEY (order_id)
        REFERENCES orders(order_id) ON DELETE CASCADE,
    CONSTRAINT fk_items_book FOREIGN KEY (book_id)
        REFERENCES books(book_id) ON DELETE RESTRICT
);

-- ---------- VIEW: sales summary per book (used in report/demo) ----------
CREATE VIEW book_sales AS
SELECT b.book_id, b.title, a.name AS author,
       COALESCE(SUM(oi.quantity), 0)                 AS copies_sold,
       COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS revenue
FROM books b
JOIN authors a          ON a.author_id = b.author_id
LEFT JOIN order_items oi ON oi.book_id = b.book_id
GROUP BY b.book_id, b.title, a.name;

-- =============================================================
-- SAMPLE DATA
-- =============================================================
INSERT INTO authors (name, country) VALUES
('George Orwell', 'United Kingdom'),
('Jane Austen', 'United Kingdom'),
('Haruki Murakami', 'Japan'),
('Chimamanda Ngozi Adichie', 'Nigeria'),
('Gabriel Garcia Marquez', 'Colombia');

INSERT INTO books (title, author_id, isbn, genre, price, stock) VALUES
('1984', 1, '9780451524935', 'Dystopian', 9.99, 25),
('Animal Farm', 1, '9780451526342', 'Satire', 7.49, 30),
('Pride and Prejudice', 2, '9780141439518', 'Romance', 8.99, 20),
('Kafka on the Shore', 3, '9781400079278', 'Fiction', 15.95, 12),
('Norwegian Wood', 3, '9780375704024', 'Fiction', 14.00, 10),
('Americanah', 4, '9780307455925', 'Fiction', 16.00, 8),
('One Hundred Years of Solitude', 5, '9780060883287', 'Magical Realism', 17.99, 15);

INSERT INTO customers (name, email, phone) VALUES
('Alice Johnson', 'alice@example.com', '555-0101'),
('Brian Lee', 'brian@example.com', '555-0102'),
('Carla Gomez', 'carla@example.com', '555-0103');

INSERT INTO orders (customer_id, status) VALUES (1, 'Delivered'), (2, 'Pending');

INSERT INTO order_items (order_id, book_id, quantity, unit_price) VALUES
(1, 1, 2, 9.99),
(1, 3, 1, 8.99),
(2, 4, 1, 15.95);

-- Quick check
SELECT * FROM book_sales;
