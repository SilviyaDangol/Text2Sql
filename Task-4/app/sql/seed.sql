-- Drop tables safely (order + CASCADE matters)
DROP TABLE IF EXISTS orderdetails CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS employees CASCADE;
DROP TABLE IF EXISTS offices CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS productlines CASCADE;

-- Tables
CREATE TABLE productlines (
"productLine" VARCHAR(50) PRIMARY KEY,
"textDescription" VARCHAR(4000),
"htmlDescription" TEXT,
"image" BYTEA
);

CREATE TABLE products (
"productCode" VARCHAR(15) PRIMARY KEY,
"productName" VARCHAR(70) NOT NULL,
"productLine" VARCHAR(50) NOT NULL,
"productScale" VARCHAR(10) NOT NULL,
"productVendor" VARCHAR(50) NOT NULL,
"productDescription" TEXT NOT NULL,
"quantityInStock" INTEGER NOT NULL,
"buyPrice" NUMERIC(10,2) NOT NULL,
"MSRP" NUMERIC(10,2) NOT NULL,
FOREIGN KEY ("productLine") REFERENCES productlines("productLine")
);

CREATE TABLE offices (
"officeCode" VARCHAR(10) PRIMARY KEY,
"city" VARCHAR(50) NOT NULL,
"phone" VARCHAR(50) NOT NULL,
"addressLine1" VARCHAR(50) NOT NULL,
"addressLine2" VARCHAR(50),
"state" VARCHAR(50),
"country" VARCHAR(50) NOT NULL,
"postalCode" VARCHAR(15) NOT NULL,
"territory" VARCHAR(10) NOT NULL
);

CREATE TABLE employees (
"employeeNumber" INTEGER PRIMARY KEY,
"lastName" VARCHAR(50) NOT NULL,
"firstName" VARCHAR(50) NOT NULL,
"extension" VARCHAR(10) NOT NULL,
"email" VARCHAR(100) NOT NULL,
"officeCode" VARCHAR(10) NOT NULL,
"reportsTo" INTEGER,
"jobTitle" VARCHAR(50) NOT NULL,
FOREIGN KEY ("reportsTo") REFERENCES employees("employeeNumber"),
FOREIGN KEY ("officeCode") REFERENCES offices("officeCode")
);

CREATE TABLE customers (
"customerNumber" INTEGER PRIMARY KEY,
"customerName" VARCHAR(50) NOT NULL,
"contactLastName" VARCHAR(50) NOT NULL,
"contactFirstName" VARCHAR(50) NOT NULL,
"phone" VARCHAR(50) NOT NULL,
"addressLine1" VARCHAR(50) NOT NULL,
"addressLine2" VARCHAR(50),
"city" VARCHAR(50) NOT NULL,
"state" VARCHAR(50),
"postalCode" VARCHAR(15),
"country" VARCHAR(50) NOT NULL,
"salesRepEmployeeNumber" INTEGER,
"creditLimit" NUMERIC(10,2),
FOREIGN KEY ("salesRepEmployeeNumber") REFERENCES employees("employeeNumber")
);

CREATE TABLE payments (
"customerNumber" INTEGER,
"checkNumber" VARCHAR(50),
"paymentDate" DATE NOT NULL,
"amount" NUMERIC(10,2) NOT NULL,
PRIMARY KEY ("customerNumber", "checkNumber"),
FOREIGN KEY ("customerNumber") REFERENCES customers("customerNumber")
);

CREATE TABLE orders (
"orderNumber" INTEGER PRIMARY KEY,
"orderDate" DATE NOT NULL,
"requiredDate" DATE NOT NULL,
"shippedDate" DATE,
"status" VARCHAR(15) NOT NULL,
"comments" TEXT,
"customerNumber" INTEGER NOT NULL,
FOREIGN KEY ("customerNumber") REFERENCES customers("customerNumber")
);

CREATE TABLE orderdetails (
"orderNumber" INTEGER,
"productCode" VARCHAR(15),
"quantityOrdered" INTEGER NOT NULL,
"priceEach" NUMERIC(10,2) NOT NULL,
"orderLineNumber" SMALLINT NOT NULL,
PRIMARY KEY ("orderNumber", "productCode"),
FOREIGN KEY ("orderNumber") REFERENCES orders("orderNumber"),
FOREIGN KEY ("productCode") REFERENCES products("productCode")
);

-- Sample seed data for demo queries
INSERT INTO productlines ("productLine", "textDescription") VALUES
('Classic Cars', 'Vintage automobiles'),
('Motorcycles', 'Two-wheel vehicles');

INSERT INTO products ("productCode", "productName", "productLine", "productScale", "productVendor", "productDescription", "quantityInStock", "buyPrice", "MSRP") VALUES
('S10_1678', '1969 Harley Davidson Ultimate Chopper', 'Motorcycles', '1:10', 'Min Lin Diecast', 'Classic motorcycle', 7933, 48.81, 95.70),
('S10_1949', '1952 Alpine Renault 1300', 'Classic Cars', '1:10', 'Classic Car Collectables', 'Vintage car', 7305, 98.58, 214.30);

INSERT INTO offices ("officeCode", "city", "phone", "addressLine1", "country", "postalCode", "territory") VALUES
('1', 'San Francisco', '100', '100 Market Street', 'USA', '94080', 'NA'),
('2', 'Boston', '200', '1550 Court Place', 'USA', '02107', 'NA');

INSERT INTO employees ("employeeNumber", "lastName", "firstName", "extension", "email", "officeCode", "jobTitle") VALUES
(1002, 'Murphy', 'Diane', 'x5800', 'dmurphy@classicmodelcars.com', '1', 'President'),
(1056, 'Patterson', 'Mary', 'x4611', 'mpatterson@classicmodelcars.com', '1', 'VP Sales');

INSERT INTO customers ("customerNumber", "customerName", "contactLastName", "contactFirstName", "phone", "addressLine1", "city", "country", "salesRepEmployeeNumber", "creditLimit") VALUES
(103, 'Atelier graphique', 'Schmitt', 'Carine', '40.32.2555', '54, rue Royale', 'Nantes', 'France', 1056, 21000.00),
(112, 'Signal Gift Stores', 'King', 'Jean', '650555183', '70200 N. Dalles Hwy', 'Las Vegas', 'USA', 1056, 71800.00);

INSERT INTO orders ("orderNumber", "orderDate", "requiredDate", "shippedDate", "status", "customerNumber") VALUES
(10100, '2003-01-06', '2003-01-13', '2003-01-10', 'Shipped', 103),
(10101, '2003-01-09', '2003-01-18', '2003-01-11', 'Shipped', 112);

INSERT INTO orderdetails ("orderNumber", "productCode", "quantityOrdered", "priceEach", "orderLineNumber") VALUES
(10100, 'S10_1678', 30, 136.00, 1),
(10101, 'S10_1949', 50, 33.30, 1);

INSERT INTO payments ("customerNumber", "checkNumber", "paymentDate", "amount") VALUES
(103, 'HQ336336', '2004-10-19', 6066.78),
(112, 'JM555205', '2004-11-05', 8765.00);
