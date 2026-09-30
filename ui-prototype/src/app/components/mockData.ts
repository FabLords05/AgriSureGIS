export type GrowthStage = "Seedling" | "Vegetative" | "Reproductive" | "Ripening";
export type SignalNo = 1 | 2 | 3 | 4 | 5;

export interface FarmerRecord {
  rowId: number;
  farmerId: string;
  insuredName: string;
  municipality: string;
  province: string;
  barangay: string;
  farmId: string;
  areaHectare: number;
  planted: boolean;
  plantingDate: string;
  growthStage: GrowthStage;
  cropType: string;
  sumInsured: number;
  signalNo: SignalNo;
  periodOfExposure: number;
  windVelocityMin: number;
  windVelocityMax: number;
  indemnityFactor: number;
  indemnityPayment: number;
  mapCoords: [number, number][];
}

export interface TCBBulletin {
  id: string;
  bulletinNo: string;
  cycloneName: string;
  issuedBy: string;
  issueDateTime: string;
  signalNo: SignalNo;
  windVelocityRange: string;
  affectedAreas: string[];
  status: "downloading" | "downloaded" | "parsed" | "processed";
  fileSize: string;
  version: number;
}

export interface AppNotification {
  id: string;
  type: "bulletin" | "warning" | "info" | "success";
  title: string;
  message: string;
  timestamp: string;
  read: boolean;
}

export const DAMAGE_FACTORS: Record<GrowthStage, Record<number, number>> = {
  Seedling:      { 1: 15, 2: 30, 3: 55 },
  Vegetative:    { 1: 10, 2: 25, 3: 45 },
  Reproductive:  { 1: 20, 2: 40, 3: 65 },
  Ripening:      { 1: 15, 2: 30, 3: 50 },
};

export const SIGNAL_WIND_RANGES: Record<number, string> = {
  1: "30–60 kph",
  2: "61–120 kph",
  3: "121–185 kph",
  4: "186–220 kph",
  5: ">220 kph",
};

// Farm polygon coordinates for 800×480 canvas
const P: Record<string, [number, number][]> = {
  F001: [[355,195],[395,190],[400,220],[360,225]],
  F002: [[310,225],[350,220],[355,252],[315,257]],
  F003: [[405,205],[445,200],[450,232],[410,237]],
  F004: [[340,258],[380,253],[385,282],[345,287]],
  F005: [[365,162],[405,157],[410,187],[370,192]],
  F006: [[466,252],[506,247],[511,277],[471,282]],
  F007: [[516,266],[556,261],[561,291],[521,296]],
  F008: [[481,292],[521,287],[526,317],[486,322]],
  F009: [[254,317],[294,312],[299,342],[259,347]],
  F010: [[304,336],[344,331],[349,361],[309,366]],
  F011: [[264,357],[304,352],[309,382],[269,387]],
  F012: [[224,340],[264,335],[269,365],[229,370]],
  F013: [[164,376],[204,371],[209,401],[169,406]],
  F014: [[214,396],[254,391],[259,421],[219,426]],
  F015: [[174,416],[214,411],[219,441],[179,446]],
  F016: [[531,346],[571,341],[576,371],[536,376]],
  F017: [[576,366],[616,361],[621,391],[581,396]],
  F018: [[546,386],[586,381],[591,411],[551,416]],
  F019: [[596,416],[636,411],[641,441],[601,446]],
  F020: [[611,441],[651,436],[656,466],[616,471]],
};

export const mockFarmers: FarmerRecord[] = [
  // Naga City – Signal 2  (RSBSA ₱25,000/ha)
  { rowId:1,  farmerId:"PCIC-2024-00001", insuredName:"Juan A. Dela Cruz",       municipality:"Naga City",  province:"Camarines Sur", barangay:"Triangulo",    farmId:"F001", areaHectare:2.50, planted:true,  plantingDate:"2024-09-10", growthStage:"Vegetative",   cropType:"Rice", sumInsured:62500,  signalNo:2, periodOfExposure:6,  windVelocityMin:61,  windVelocityMax:120, indemnityFactor:25, indemnityPayment:15625, mapCoords:P.F001 },
  { rowId:2,  farmerId:"PCIC-2024-00002", insuredName:"Maria B. Santos",         municipality:"Naga City",  province:"Camarines Sur", barangay:"Pacol",        farmId:"F002", areaHectare:1.75, planted:true,  plantingDate:"2024-09-15", growthStage:"Reproductive", cropType:"Rice", sumInsured:43750,  signalNo:2, periodOfExposure:6,  windVelocityMin:61,  windVelocityMax:120, indemnityFactor:40, indemnityPayment:17500, mapCoords:P.F002 },
  { rowId:3,  farmerId:"PCIC-2024-00003", insuredName:"Pedro C. Reyes",          municipality:"Naga City",  province:"Camarines Sur", barangay:"Sabang",       farmId:"F003", areaHectare:3.00, planted:true,  plantingDate:"2024-08-25", growthStage:"Ripening",     cropType:"Rice", sumInsured:75000,  signalNo:2, periodOfExposure:6,  windVelocityMin:61,  windVelocityMax:120, indemnityFactor:30, indemnityPayment:22500, mapCoords:P.F003 },
  { rowId:4,  farmerId:"PCIC-2024-00004", insuredName:"Ana D. Garcia",           municipality:"Naga City",  province:"Camarines Sur", barangay:"Dayangdang",   farmId:"F004", areaHectare:1.25, planted:true,  plantingDate:"2024-09-20", growthStage:"Seedling",     cropType:"Rice", sumInsured:31250,  signalNo:2, periodOfExposure:6,  windVelocityMin:61,  windVelocityMax:120, indemnityFactor:30, indemnityPayment:9375,  mapCoords:P.F004 },
  { rowId:5,  farmerId:"PCIC-2024-00005", insuredName:"Jose E. Bautista",        municipality:"Naga City",  province:"Camarines Sur", barangay:"Balatas",      farmId:"F005", areaHectare:2.00, planted:true,  plantingDate:"2024-09-05", growthStage:"Vegetative",   cropType:"Rice", sumInsured:50000,  signalNo:1, periodOfExposure:3,  windVelocityMin:30,  windVelocityMax:60,  indemnityFactor:10, indemnityPayment:5000,  mapCoords:P.F005 },
  // Pili – Signal 2
  { rowId:6,  farmerId:"PCIC-2024-00006", insuredName:"Rosa F. Mendoza",         municipality:"Pili",       province:"Camarines Sur", barangay:"San Jose",     farmId:"F006", areaHectare:2.75, planted:true,  plantingDate:"2024-09-12", growthStage:"Reproductive", cropType:"Rice", sumInsured:68750,  signalNo:2, periodOfExposure:9,  windVelocityMin:61,  windVelocityMax:120, indemnityFactor:40, indemnityPayment:27500, mapCoords:P.F006 },
  { rowId:7,  farmerId:"PCIC-2024-00007", insuredName:"Carlos G. Villanueva",    municipality:"Pili",       province:"Camarines Sur", barangay:"Palestina",    farmId:"F007", areaHectare:1.50, planted:true,  plantingDate:"2024-09-18", growthStage:"Seedling",     cropType:"Rice", sumInsured:37500,  signalNo:2, periodOfExposure:9,  windVelocityMin:61,  windVelocityMax:120, indemnityFactor:30, indemnityPayment:11250, mapCoords:P.F007 },
  { rowId:8,  farmerId:"PCIC-2024-00008", insuredName:"Elena H. Torres",         municipality:"Pili",       province:"Camarines Sur", barangay:"Tinangis",     farmId:"F008", areaHectare:3.25, planted:true,  plantingDate:"2024-08-30", growthStage:"Ripening",     cropType:"Rice", sumInsured:81250,  signalNo:2, periodOfExposure:9,  windVelocityMin:61,  windVelocityMax:120, indemnityFactor:30, indemnityPayment:24375, mapCoords:P.F008 },
  // Libmanan – Signal 2
  { rowId:9,  farmerId:"PCIC-2024-00009", insuredName:"Roberto I. Castillo",     municipality:"Libmanan",   province:"Camarines Sur", barangay:"Palangon",     farmId:"F009", areaHectare:4.00, planted:true,  plantingDate:"2024-09-08", growthStage:"Vegetative",   cropType:"Rice", sumInsured:100000, signalNo:2, periodOfExposure:6,  windVelocityMin:61,  windVelocityMax:120, indemnityFactor:25, indemnityPayment:25000, mapCoords:P.F009 },
  { rowId:10, farmerId:"PCIC-2024-00010", insuredName:"Lourdes J. Aquino",       municipality:"Libmanan",   province:"Camarines Sur", barangay:"San Vicente",  farmId:"F010", areaHectare:2.25, planted:true,  plantingDate:"2024-09-22", growthStage:"Seedling",     cropType:"Rice", sumInsured:56250,  signalNo:2, periodOfExposure:6,  windVelocityMin:61,  windVelocityMax:120, indemnityFactor:30, indemnityPayment:16875, mapCoords:P.F010 },
  { rowId:11, farmerId:"PCIC-2024-00011", insuredName:"Antonio K. Ramos",        municipality:"Libmanan",   province:"Camarines Sur", barangay:"Mabini",       farmId:"F011", areaHectare:1.75, planted:true,  plantingDate:"2024-09-14", growthStage:"Reproductive", cropType:"Rice", sumInsured:43750,  signalNo:2, periodOfExposure:6,  windVelocityMin:61,  windVelocityMax:120, indemnityFactor:40, indemnityPayment:17500, mapCoords:P.F011 },
  { rowId:12, farmerId:"PCIC-2024-00012", insuredName:"Felicia L. Navarro",      municipality:"Libmanan",   province:"Camarines Sur", barangay:"Taban",        farmId:"F012", areaHectare:3.00, planted:false, plantingDate:"—",          growthStage:"Seedling",     cropType:"Rice", sumInsured:0,      signalNo:1, periodOfExposure:0,  windVelocityMin:0,   windVelocityMax:0,   indemnityFactor:0,  indemnityPayment:0,     mapCoords:P.F012 },
  // Sipocot – Signal 1
  { rowId:13, farmerId:"PCIC-2024-00013", insuredName:"Manuel M. Navarro",       municipality:"Sipocot",    province:"Camarines Sur", barangay:"Impig",        farmId:"F013", areaHectare:2.00, planted:true,  plantingDate:"2024-09-10", growthStage:"Vegetative",   cropType:"Rice", sumInsured:50000,  signalNo:1, periodOfExposure:3,  windVelocityMin:30,  windVelocityMax:60,  indemnityFactor:10, indemnityPayment:5000,  mapCoords:P.F013 },
  { rowId:14, farmerId:"PCIC-2024-00014", insuredName:"Gloria N. Cruz",          municipality:"Sipocot",    province:"Camarines Sur", barangay:"Cabuyao",      farmId:"F014", areaHectare:1.50, planted:true,  plantingDate:"2024-09-25", growthStage:"Seedling",     cropType:"Rice", sumInsured:37500,  signalNo:1, periodOfExposure:3,  windVelocityMin:30,  windVelocityMax:60,  indemnityFactor:15, indemnityPayment:5625,  mapCoords:P.F014 },
  { rowId:15, farmerId:"PCIC-2024-00015", insuredName:"Ricardo O. Flores",       municipality:"Sipocot",    province:"Camarines Sur", barangay:"Patag",        farmId:"F015", areaHectare:2.75, planted:true,  plantingDate:"2024-08-28", growthStage:"Ripening",     cropType:"Rice", sumInsured:68750,  signalNo:1, periodOfExposure:3,  windVelocityMin:30,  windVelocityMax:60,  indemnityFactor:15, indemnityPayment:10313, mapCoords:P.F015 },
  // Goa – Signal 3
  { rowId:16, farmerId:"PCIC-2024-00016", insuredName:"Corazon P. Morales",      municipality:"Goa",        province:"Camarines Sur", barangay:"Otol",         farmId:"F016", areaHectare:1.25, planted:true,  plantingDate:"2024-09-15", growthStage:"Reproductive", cropType:"Rice", sumInsured:31250,  signalNo:3, periodOfExposure:9,  windVelocityMin:121, windVelocityMax:185, indemnityFactor:65, indemnityPayment:20313, mapCoords:P.F016 },
  { rowId:17, farmerId:"PCIC-2024-00017", insuredName:"Ernesto Q. Jimenez",      municipality:"Goa",        province:"Camarines Sur", barangay:"Matacla",      farmId:"F017", areaHectare:2.00, planted:true,  plantingDate:"2024-09-08", growthStage:"Vegetative",   cropType:"Rice", sumInsured:50000,  signalNo:3, periodOfExposure:9,  windVelocityMin:121, windVelocityMax:185, indemnityFactor:45, indemnityPayment:22500, mapCoords:P.F017 },
  { rowId:18, farmerId:"PCIC-2024-00018", insuredName:"Rosario R. Espinosa",     municipality:"Goa",        province:"Camarines Sur", barangay:"Bagalaya",     farmId:"F018", areaHectare:3.50, planted:true,  plantingDate:"2024-09-01", growthStage:"Ripening",     cropType:"Rice", sumInsured:87500,  signalNo:3, periodOfExposure:9,  windVelocityMin:121, windVelocityMax:185, indemnityFactor:50, indemnityPayment:43750, mapCoords:P.F018 },
  // Lagonoy – Signal 3
  { rowId:19, farmerId:"PCIC-2024-00019", insuredName:"Domingo S. Luna",         municipality:"Lagonoy",    province:"Camarines Sur", barangay:"Agosais",      farmId:"F019", areaHectare:1.75, planted:true,  plantingDate:"2024-09-18", growthStage:"Seedling",     cropType:"Rice", sumInsured:43750,  signalNo:3, periodOfExposure:12, windVelocityMin:121, windVelocityMax:185, indemnityFactor:55, indemnityPayment:24063, mapCoords:P.F019 },
  { rowId:20, farmerId:"PCIC-2024-00020", insuredName:"Teresita T. Miranda",     municipality:"Lagonoy",    province:"Camarines Sur", barangay:"Agos-os",      farmId:"F020", areaHectare:4.50, planted:true,  plantingDate:"2024-09-02", growthStage:"Ripening",     cropType:"Rice", sumInsured:112500, signalNo:3, periodOfExposure:12, windVelocityMin:121, windVelocityMax:185, indemnityFactor:50, indemnityPayment:56250, mapCoords:P.F020 },
];

export const mockBulletins: TCBBulletin[] = [
  { id:"tcb-001", bulletinNo:"TCB No. 1",  cycloneName:"Typhoon Pepito", issuedBy:"PAGASA-DOST", issueDateTime:"01 Nov 2024 00:00 PHT", signalNo:1, windVelocityRange:"30–60 kph",   affectedAreas:["Camarines Norte","Camarines Sur","Catanduanes","Albay"], status:"processed",   fileSize:"842 KB",  version:1 },
  { id:"tcb-002", bulletinNo:"TCB No. 2",  cycloneName:"Typhoon Pepito", issuedBy:"PAGASA-DOST", issueDateTime:"01 Nov 2024 03:00 PHT", signalNo:2, windVelocityRange:"61–120 kph",  affectedAreas:["Camarines Sur","Albay","Sorsogon"],                       status:"processed",   fileSize:"1.1 MB",  version:2 },
  { id:"tcb-003", bulletinNo:"TCB No. 3",  cycloneName:"Typhoon Pepito", issuedBy:"PAGASA-DOST", issueDateTime:"01 Nov 2024 06:00 PHT", signalNo:2, windVelocityRange:"61–120 kph",  affectedAreas:["Camarines Sur","Albay"],                                  status:"processed",   fileSize:"1.3 MB",  version:3 },
  { id:"tcb-004", bulletinNo:"TCB No. 4",  cycloneName:"Typhoon Pepito", issuedBy:"PAGASA-DOST", issueDateTime:"01 Nov 2024 09:00 PHT", signalNo:3, windVelocityRange:"121–185 kph", affectedAreas:["Camarines Sur","Quezon","Aurora"],                        status:"parsed",      fileSize:"1.2 MB",  version:4 },
  { id:"tcb-005", bulletinNo:"TCB No. 5",  cycloneName:"Typhoon Pepito", issuedBy:"PAGASA-DOST", issueDateTime:"01 Nov 2024 12:00 PHT", signalNo:3, windVelocityRange:"121–185 kph", affectedAreas:["Camarines Sur","Quezon"],                                 status:"downloaded",  fileSize:"1.4 MB",  version:5 },
  { id:"tcb-006", bulletinNo:"TCB No. 6",  cycloneName:"Typhoon Pepito", issuedBy:"PAGASA-DOST", issueDateTime:"01 Nov 2024 15:00 PHT", signalNo:2, windVelocityRange:"61–120 kph",  affectedAreas:["Camarines Sur","Quezon"],                                 status:"downloading", fileSize:"—",       version:6 },
];

export const mockNotifications: AppNotification[] = [
  { id:"n1", type:"bulletin", title:"New TCB Parsed",     message:"TCB No. 6 for Typhoon Pepito has been downloaded and parsed successfully.",       timestamp:"15:02 PHT", read:false },
  { id:"n2", type:"warning",  title:"Signal No. 3 Alert", message:"Camarines Sur is now under Signal No. 3. 3 farms in Goa and Lagonoy affected.",    timestamp:"09:11 PHT", read:false },
  { id:"n3", type:"success",  title:"Analysis Complete",  message:"Automated exposure calculation completed for 19 of 20 farmer records.",            timestamp:"08:55 PHT", read:true  },
  { id:"n4", type:"info",     title:"PAGASA Parser Active","message":"System is actively monitoring PAGASA website for new TCB updates every 3 hours.", timestamp:"00:01 PHT", read:true  },
];
