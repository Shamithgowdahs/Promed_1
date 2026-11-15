/**
 * PROMED — Smart Medical Store Management System
 * DEMONSTRATION DATASET (Step 1 Prototype)
 * 
 * NOTE: All data contained in this file is strictly DEMONSTRATION DATA
 * for UI/UX testing and workflow prototyping.
 * It is NOT connected to any live hospital system, medical records,
 * or real inventory database.
 */

const PROMED_DEMO_DATA = {
  isDemoEnvironment: true,
  lastUpdated: "2026-10-25 09:30 AM",
  pharmacyInfo: {
    name: "PROMED Hospital Branch Pharmacy",
    location: "Block B - Ground Floor Dispensary (Near Emergency Wing)",
    shift: "Morning Shift (08:00 - 16:00)"
  },
  metrics: {
    totalRegisteredMedicines: 1428,
    totalAvailableStock: 18650,
    todaySalesSummary: {
      totalAmount: 2845.50,
      currency: "$",
      totalInvoices: 84,
      trend: "+12.4% vs yesterday"
    },
    lowStockCount: 9
  },
  storageBoxes: [
    {
      id: "A1",
      label: "Box A1",
      category: "Critical Injectables & Antibiotics",
      colorCode: "#34d399",
      accentClass: "box-code-a1",
      totalCapacity: 40,
      currentOccupancy: 34,
      percentage: 85,
      ledStatus: "Active Ready (Green Pulse)",
      temperatureZone: "Room Temp (15-25°C)",
      sampleMedicines: [
        { name: "Augmentin 625mg (Amox/Clav)", stock: 145, barcode: "8901234567890" },
        { name: "Ceftriaxone 1g Injection", stock: 68, barcode: "8901234567891" },
        { name: "Azithromycin 500mg", stock: 92, barcode: "8901234567892" },
        { name: "Meropenem 1g IV", stock: 24, barcode: "8901234567893" }
      ]
    },
    {
      id: "A2",
      label: "Box A2",
      category: "Cardiovascular & Chronic Care",
      colorCode: "#38bdf8",
      accentClass: "box-code-a2",
      totalCapacity: 35,
      currentOccupancy: 21,
      percentage: 60,
      ledStatus: "Standby (Cyan Glow)",
      temperatureZone: "Standard Shelf (<25°C)",
      sampleMedicines: [
        { name: "Atorvastatin 20mg", stock: 210, barcode: "8902345678901" },
        { name: "Metformin HCl 500mg", stock: 350, barcode: "8902345678902" },
        { name: "Amlodipine 5mg", stock: 180, barcode: "8902345678903" },
        { name: "Telmisartan 40mg", stock: 115, barcode: "8902345678904" }
      ]
    },
    {
      id: "B1",
      label: "Box B1",
      category: "Analgesics & Antipyretics (Fast Movers)",
      colorCode: "#a78bfa",
      accentClass: "box-code-b1",
      totalCapacity: 50,
      currentOccupancy: 46,
      percentage: 92,
      ledStatus: "Active Ready (Purple Aura)",
      temperatureZone: "Ambient Shelf",
      sampleMedicines: [
        { name: "Dolo 650 (Paracetamol)", stock: 850, barcode: "8903456789012" },
        { name: "Ibuprofen 400mg", stock: 320, barcode: "8903456789013" },
        { name: "Tramadol 50mg Tablets", stock: 75, barcode: "8903456789014" },
        { name: "Diclofenac Sodium Gel 30g", stock: 42, barcode: "8903456789015" }
      ]
    },
    {
      id: "B2",
      label: "Box B2",
      category: "Respiratory & Emergency Inhalers",
      colorCode: "#f472b6",
      accentClass: "box-code-b2",
      totalCapacity: 30,
      currentOccupancy: 14,
      percentage: 46,
      ledStatus: "Low Stock Alert (Rose Pulse)",
      temperatureZone: "Cool Dry Place (15-20°C)",
      sampleMedicines: [
        { name: "Salbutamol Inhaler 100mcg", stock: 8, barcode: "8904567890123" }, // Low stock!
        { name: "Budesonide Respules 0.5mg", stock: 65, barcode: "8904567890124" },
        { name: "Montelukast Sodium 10mg", stock: 190, barcode: "8904567890125" },
        { name: "Levocetirizine 5mg", stock: 140, barcode: "8904567890126" }
      ]
    }
  ],
  medicinesList: [
    {
      id: "MED-001",
      name: "Augmentin 625mg",
      generic: "Amoxicillin + Clavulanic Acid (500mg/125mg)",
      category: "Antibiotic",
      storageBox: "A1",
      shelfRow: "Row 1, Bin 4",
      stockQuantity: 145,
      minThreshold: 40,
      unitPrice: 18.50,
      batchNumber: "AG-98214",
      expiryDate: "2027-08-31",
      barcode: "8901234567890",
      status: "In Stock"
    },
    {
      id: "MED-002",
      name: "Dolo 650",
      generic: "Paracetamol (Acetaminophen) 650mg",
      category: "Analgesic / Antipyretic",
      storageBox: "B1",
      shelfRow: "Row 1, Bin 1",
      stockQuantity: 850,
      minThreshold: 100,
      unitPrice: 2.20,
      batchNumber: "DL-44120",
      expiryDate: "2028-03-31",
      barcode: "8903456789012",
      status: "In Stock"
    },
    {
      id: "MED-003",
      name: "Salbutamol Inhaler 100mcg",
      generic: "Salbutamol Sulfate 100mcg/actuation",
      category: "Respiratory / Bronchodilator",
      storageBox: "B2",
      shelfRow: "Row 3, Bin 2",
      stockQuantity: 8,
      minThreshold: 25,
      unitPrice: 14.75,
      batchNumber: "SB-11029",
      expiryDate: "2027-01-15",
      barcode: "8904567890123",
      status: "Low Stock"
    },
    {
      id: "MED-004",
      name: "Atorvastatin 20mg",
      generic: "Atorvastatin Calcium 20mg",
      category: "Cardiovascular / Statin",
      storageBox: "A2",
      shelfRow: "Row 2, Bin 3",
      stockQuantity: 210,
      minThreshold: 50,
      unitPrice: 11.00,
      batchNumber: "AT-77312",
      expiryDate: "2027-11-30",
      barcode: "8902345678901",
      status: "In Stock"
    },
    {
      id: "MED-005",
      name: "Ceftriaxone 1g Injection",
      generic: "Ceftriaxone Sodium 1g Vial",
      category: "Cephalosporin Antibiotic",
      storageBox: "A1",
      shelfRow: "Row 2, Bin 1",
      stockQuantity: 68,
      minThreshold: 20,
      unitPrice: 24.00,
      batchNumber: "CF-30912",
      expiryDate: "2026-12-31",
      barcode: "8901234567891",
      status: "In Stock"
    },
    {
      id: "MED-006",
      name: "Metformin HCl 500mg",
      generic: "Metformin Hydrochloride 500mg ER",
      category: "Antidiabetic",
      storageBox: "A2",
      shelfRow: "Row 1, Bin 2",
      stockQuantity: 350,
      minThreshold: 80,
      unitPrice: 3.40,
      batchNumber: "MF-82910",
      expiryDate: "2027-09-15",
      barcode: "8902345678902",
      status: "In Stock"
    },
    {
      id: "MED-007",
      name: "Budesonide Respules 0.5mg",
      generic: "Budesonide Inhalation Suspension 2ml",
      category: "Respiratory Corticosteroid",
      storageBox: "B2",
      shelfRow: "Row 1, Bin 4",
      stockQuantity: 65,
      minThreshold: 20,
      unitPrice: 16.80,
      batchNumber: "BD-55102",
      expiryDate: "2027-05-20",
      barcode: "8904567890124",
      status: "In Stock"
    },
    {
      id: "MED-008",
      name: "Tramadol 50mg",
      generic: "Tramadol Hydrochloride 50mg",
      category: "Opioid Analgesic (Schedule H)",
      storageBox: "B1",
      shelfRow: "Row 3, Bin 1 (Locked)",
      stockQuantity: 75,
      minThreshold: 30,
      unitPrice: 8.50,
      batchNumber: "TR-00412",
      expiryDate: "2027-04-10",
      barcode: "8903456789014",
      status: "In Stock"
    },
    {
      id: "MED-009",
      name: "Azithromycin 500mg",
      generic: "Azithromycin Dihydrate 500mg",
      category: "Macrolide Antibiotic",
      storageBox: "A1",
      shelfRow: "Row 3, Bin 2",
      stockQuantity: 92,
      minThreshold: 30,
      unitPrice: 15.20,
      batchNumber: "AZ-66190",
      expiryDate: "2027-10-31",
      barcode: "8901234567892",
      status: "In Stock"
    },
    {
      id: "MED-010",
      name: "Pantoprazole 40mg",
      generic: "Pantoprazole Sodium Gastro-resistant",
      category: "Proton Pump Inhibitor (Gastro)",
      storageBox: "B1",
      shelfRow: "Row 2, Bin 3",
      stockQuantity: 12,
      minThreshold: 50,
      unitPrice: 7.90,
      batchNumber: "PN-19230",
      expiryDate: "2026-11-20",
      barcode: "8903456789016",
      status: "Low Stock"
    }
  ],
  recentActivity: [
    {
      id: "ACT-101",
      type: "sale",
      iconType: "sale",
      title: "Dispensed 2 strips Augmentin 625mg",
      detail: "Prescription verification complete • Located in Storage Box A1 (Row 1)",
      time: "4 mins ago",
      boxTag: "Box A1",
      amount: "$37.00"
    },
    {
      id: "ACT-102",
      type: "alert",
      iconType: "alert",
      title: "Low Stock Alert: Salbutamol Inhaler",
      detail: "Current stock: 8 units remaining (Reorder threshold: 25 units)",
      time: "18 mins ago",
      boxTag: "Box B2",
      amount: "Action Req"
    },
    {
      id: "ACT-103",
      type: "scan",
      iconType: "scan",
      title: "Barcode Verified: Dolo 650 (Batch DL-44120)",
      detail: "Stock count audit matched 850 units in Storage Box B1",
      time: "35 mins ago",
      boxTag: "Box B1",
      amount: "Verified"
    },
    {
      id: "ACT-104",
      type: "sale",
      iconType: "sale",
      title: "Dispensed Atorvastatin 20mg (30 tabs)",
      detail: "Dispensary counter #2 • Retrieved from Storage Box A2",
      time: "1 hr ago",
      boxTag: "Box A2",
      amount: "$33.00"
    },
    {
      id: "ACT-105",
      type: "alert",
      iconType: "alert",
      title: "Low Stock Threshold: Pantoprazole 40mg",
      detail: "Only 12 strips remaining in Box B1 • Auto-added to Reorder draft",
      time: "2 hrs ago",
      boxTag: "Box B1",
      amount: "Reorder"
    }
  ]
};

// Freeze the demo data object to prevent accidental runtime mutations
Object.freeze(PROMED_DEMO_DATA);
